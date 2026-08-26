import * as core from '@actions/core'
import {getExecOutput} from '@actions/exec'
import {PullRequest} from '@octokit/webhooks-types'

import {File} from './file'

// Compares the API's changed-file list against the same list derived locally from
// the pull request's merge commit, and reports disagreement without acting on it.
// The API result stays authoritative, so a wrong local answer can only produce a
// log line. Removing the API call later is only safe once this has run quiet
// across the PR shapes no offline sample can reach: merged PRs, very large diffs,
// and PRs GitHub has not finished computing a merge ref for.
//
// PostHog/posthog#55830 detected changes from `base.sha..HEAD`, which reports every
// commit the branch picked up when master was merged into it as the PR's own work.
// The merge commit's first parent is the base GitHub actually merged against, so
// `HEAD^1..HEAD` is the PR's own changes and matches what the API returns.

const MERGE_REF_FETCH_DEPTH = 2

type Verdict = 'match' | 'mismatch' | 'unavailable'

interface ShadowResult {
  verdict: Verdict
  reason?: string
  apiCount: number
  gitCount?: number
  onlyInApi?: string[]
  onlyInGit?: string[]
}

async function git(args: string[]): Promise<{code: number; out: string}> {
  const res = await getExecOutput('git', args, {ignoreReturnCode: true, silent: true})
  return {code: res.exitCode, out: res.stdout.trim()}
}

// The merge ref is not guaranteed to be present or current: a shallow checkout has
// no parents, and GitHub recomputes the ref asynchronously after a push. Requiring
// the second parent to equal the head SHA rejects a stale ref rather than reading
// it as this PR's changes.
async function localChangedFiles(pr: PullRequest): Promise<string[]> {
  const fetched = await git([
    'fetch',
    '--no-tags',
    '--filter=blob:none',
    `--depth=${MERGE_REF_FETCH_DEPTH}`,
    'origin',
    `refs/pull/${pr.number}/merge`
  ])
  if (fetched.code !== 0) {
    throw new Error('no merge ref')
  }

  const parents = await git(['rev-list', '--parents', '-n', '1', 'FETCH_HEAD'])
  if (parents.code !== 0 || parents.out.split(/\s+/).length !== 3) {
    throw new Error('merge ref has no second parent')
  }

  const head = await git(['rev-parse', 'FETCH_HEAD^2'])
  if (head.code !== 0 || head.out !== pr.head.sha) {
    throw new Error(`merge ref is stale (^2=${head.out.slice(0, 8)}, head=${pr.head.sha.slice(0, 8)})`)
  }

  // --no-renames so a rename arrives as a delete plus an add, which is the shape
  // the API path builds by hand from `previous_filename`.
  const diff = await git(['diff', '--no-renames', '--name-only', 'FETCH_HEAD^1', 'FETCH_HEAD'])
  if (diff.code !== 0) {
    throw new Error('diff failed')
  }
  return diff.out.split('\n').filter(Boolean)
}

function compare(apiFiles: File[], gitFiles: string[]): ShadowResult {
  const api = new Set(apiFiles.map(f => f.filename))
  const local = new Set(gitFiles)
  const onlyInApi = [...api].filter(f => !local.has(f))
  const onlyInGit = [...local].filter(f => !api.has(f))
  return {
    verdict: onlyInApi.length === 0 && onlyInGit.length === 0 ? 'match' : 'mismatch',
    apiCount: api.size,
    gitCount: local.size,
    onlyInApi: onlyInApi.slice(0, 20),
    onlyInGit: onlyInGit.slice(0, 20)
  }
}

export async function compareWithMergeCommit(apiFiles: File[], pr: PullRequest): Promise<ShadowResult> {
  try {
    return compare(apiFiles, await localChangedFiles(pr))
  } catch (error) {
    return {
      verdict: 'unavailable',
      reason: error instanceof Error ? error.message : String(error),
      apiCount: apiFiles.length
    }
  }
}

// Never throws: the filter's real answer is already computed by the time this runs,
// so nothing here is worth failing a CI job over.
export async function report(apiFiles: File[], pr: PullRequest): Promise<void> {
  try {
    core.startGroup('Shadow: merge-commit change detection')
    const result = await compareWithMergeCommit(apiFiles, pr)
    if (result.verdict === 'match') {
      core.info(`shadow: match (${result.apiCount} files)`)
    } else if (result.verdict === 'unavailable') {
      core.info(`shadow: unavailable (${result.reason})`)
    } else {
      core.warning(
        `shadow: MISMATCH api=${result.apiCount} git=${result.gitCount} ` +
          `onlyInApi=${JSON.stringify(result.onlyInApi)} onlyInGit=${JSON.stringify(result.onlyInGit)}`
      )
    }
    core.setOutput('shadow_verdict', result.verdict)
  } catch (error) {
    core.info(`shadow: skipped (${error instanceof Error ? error.message : String(error)})`)
  } finally {
    core.endGroup()
  }
}
