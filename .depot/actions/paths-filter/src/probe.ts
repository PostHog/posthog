// THROWAWAY measurement scaffolding for the merge-commit change-detection rollout.
// It exists to prove, with numbers, that the merge-commit path costs zero REST
// requests and returns the same file list as the API path. Delete this module, its
// call sites in main.ts, and the workflow env blocks that switch it on before the
// merge-commit change is shipped.
//
// Two instruments, because they answer different questions:
//   - The octokit request hook counts what one invocation actually spends. It is
//     exact and cannot be contaminated by other jobs.
//   - The /rate_limit bracket reads the shared App bucket. Every job of a CI fan-out
//     draws from that one bucket concurrently, so a single job's delta is inflated by
//     its neighbours. The absolute `used` readings are still useful: across the whole
//     fan-out, max(used_after) - min(used_before) bounds what the fan-out spent.
//     GitHub documents /rate_limit as not counting against the limit it reports, so
//     sampling is free.
import {createHash} from 'crypto'
import * as core from '@actions/core'
import * as github from '@actions/github'

import {File} from './file'

const POSTHOG_HOST = 'https://us.i.posthog.com'
const EVENT_NAME = 'paths_filter_change_detection_probe'

type Mode = 'api' | 'git'

interface RateLimitSample {
  used: number
  limit: number
  reset: number
}

let apiRequests = 0
let before: RateLimitSample | null = null
let source = 'unknown'

// Which branch of getChangedFiles produced the list. 'api' after an explicit probe
// mode of 'api' means the switch worked; 'api' under mode 'git' means the merge
// commit was unusable and the action fell back.
export function setSource(value: string): void {
  source = value
}

function mode(): Mode | null {
  const value = (process.env.PATHS_FILTER_PROBE_MODE ?? '').trim().toLowerCase()
  return value === 'api' || value === 'git' ? value : null
}

export function enabled(): boolean {
  return mode() !== null
}

// The merge-commit path is the default. Only an explicit 'api' probe mode takes it
// away, so that the same commit can be measured both ways.
export function mergeCommitDiffAllowed(): boolean {
  return mode() !== 'api'
}

export function countApiRequests(octokit: {hook: {before: (name: string, fn: () => void) => void}}): void {
  if (!enabled()) {
    return
  }
  octokit.hook.before('request', () => {
    apiRequests += 1
  })
}

export async function begin(token: string): Promise<void> {
  if (!enabled()) {
    return
  }
  apiRequests = 0
  before = await sampleRateLimit(token)
}

export async function finish(token: string, files: File[]): Promise<void> {
  if (!enabled()) {
    return
  }

  const after = await sampleRateLimit(token)
  const paths = files.map(file => file.filename).sort()
  const digest = createHash('sha256').update(paths.join('\n')).digest('hex')
  const properties = {
    mode: mode(),
    detection_source: source,
    api_requests: apiRequests,
    file_count: files.length,
    files_digest: digest,
    bucket_used_before: before?.used ?? null,
    bucket_used_after: after?.used ?? null,
    bucket_delta: before && after ? after.used - before.used : null,
    bucket_limit: after?.limit ?? null,
    bucket_reset_before: before?.reset ?? null,
    bucket_reset_after: after?.reset ?? null,
    head_sha: github.context.payload.pull_request?.head?.sha ?? github.context.sha,
    // The merge commit the runner checked out. Two runs only compare if this matches:
    // GitHub recomputes refs/pull/N/merge when the base branch moves.
    checkout_sha: process.env.GITHUB_SHA ?? '',
    workflow: process.env.GITHUB_WORKFLOW ?? '',
    job: process.env.GITHUB_JOB ?? '',
    run_id: process.env.GITHUB_RUN_ID ?? '',
    run_attempt: process.env.GITHUB_RUN_ATTEMPT ?? '',
    run_number: process.env.GITHUB_RUN_NUMBER ?? '',
    pr_number: github.context.payload.pull_request?.number ?? null
  }

  core.info(`probe ${JSON.stringify(properties)}`)
  await writeSummary(properties, paths)
  await capture(properties)
}

async function sampleRateLimit(token: string): Promise<RateLimitSample | null> {
  if (!token) {
    core.warning('probe: no token, cannot read the rate-limit bucket')
    return null
  }

  try {
    const response = await fetch('https://api.github.com/rate_limit', {
      headers: {
        authorization: `Bearer ${token}`,
        accept: 'application/vnd.github+json',
        'x-github-api-version': '2022-11-28'
      }
    })
    if (!response.ok) {
      core.warning(`probe: /rate_limit returned ${response.status}`)
      return null
    }
    const body = (await response.json()) as {resources: {core: RateLimitSample}}
    return body.resources.core
  } catch (error) {
    core.warning(`probe: /rate_limit failed - ${error instanceof Error ? error.message : String(error)}`)
    return null
  }
}

async function writeSummary(properties: Record<string, unknown>, paths: string[]): Promise<void> {
  if (!process.env.GITHUB_STEP_SUMMARY) {
    return
  }

  const rows = Object.entries(properties).map(([key, value]) => `| ${key} | ${String(value)} |`)
  const markdown = [
    `### paths-filter probe: ${properties.workflow} / ${properties.job}`,
    '',
    '| field | value |',
    '| --- | --- |',
    ...rows,
    '',
    `<details><summary>changed files (${paths.length})</summary>`,
    '',
    '```',
    ...paths,
    '```',
    '',
    '</details>',
    ''
  ].join('\n')

  await core.summary.addRaw(markdown, true).write()
}

async function capture(properties: Record<string, unknown>): Promise<void> {
  const apiKey = process.env.PATHS_FILTER_PROBE_POSTHOG_TOKEN
  if (!apiKey) {
    core.info('probe: PATHS_FILTER_PROBE_POSTHOG_TOKEN not set, skipping capture')
    return
  }

  try {
    const response = await fetch(`${POSTHOG_HOST}/capture/`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        api_key: apiKey,
        event: EVENT_NAME,
        distinct_id: process.env.GITHUB_REPOSITORY ?? 'unknown',
        properties
      })
    })
    if (!response.ok) {
      core.warning(`probe: capture returned ${response.status}`)
    }
  } catch (error) {
    core.warning(`probe: capture failed - ${error instanceof Error ? error.message : String(error)}`)
  }
}
