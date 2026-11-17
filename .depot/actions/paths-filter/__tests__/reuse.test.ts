import * as core from '@actions/core'
import {PullRequest} from '@octokit/webhooks-types'

import {ApiFileRow, File, filesFromApiRow} from '../src/file'
import {Filter} from '../src/filter'
import {CheckRun, ReuseApi, ReuseConfig, ReuseInput, evaluate, loadConfig, withoutReusedKeys} from '../src/reuse'

jest.mock('@actions/core')

const PREVIOUS_HEAD = 'a'.repeat(40)
const BASE = 'b'.repeat(40)
const READY_AT = '2026-11-10T12:00:00Z'
const GATE = 'Frontend Tests Pass'

const filter = new Filter(`
frontend:
  - 'frontend/**'
docs:
  - 'docs/**'
`)

const config: ReuseConfig = {checks: [GATE], keys: ['frontend'], blockingLabels: ['run-ci-frontend'], disabled: false}

const green: CheckRun = {status: 'completed', conclusion: 'success', startedAt: '2026-11-10T13:00:00Z'}

function files(...rows: ApiFileRow[]): File[] {
  return rows.flatMap(filesFromApiRow)
}

const appFile: ApiFileRow = {filename: 'frontend/src/app.ts', status: 'modified', sha: 'app-v1'}
const backendFile: ApiFileRow = {filename: 'posthog/api.py', status: 'modified', sha: 'api-v1'}

function pullRequest(overrides: Record<string, unknown> = {}): PullRequest {
  return {
    number: 7,
    draft: false,
    labels: [],
    head: {sha: 'c'.repeat(40), ref: 'feature', repo: {full_name: 'PostHog/posthog'}},
    base: {sha: BASE, ref: 'master', repo: {full_name: 'PostHog/posthog'}},
    ...overrides
  } as unknown as PullRequest
}

function input(overrides: Partial<ReuseInput> = {}): ReuseInput {
  return {
    config,
    filter,
    files: files(appFile, backendFile),
    truncated: false,
    action: 'synchronize',
    before: PREVIOUS_HEAD,
    pr: pullRequest(),
    ...overrides
  }
}

function api(overrides: Partial<ReuseApi> = {}): () => ReuseApi {
  return () => ({
    filesAt: async () => files(appFile),
    checkRuns: async () => [green],
    readyForReviewAt: async () => READY_AT,
    ...overrides
  })
}

describe('reuse of an earlier passing result', () => {
  test('a push that leaves the scoped inputs alone reuses the previous head', async () => {
    const decision = await evaluate(input(), api())

    expect(decision).toMatchObject({reuse: true, reason: 'reused', previousSha: PREVIOUS_HEAD, keys: ['frontend']})
  })

  test('a rebase that changes only the base blob of a deleted input still reuses', async () => {
    const decision = await evaluate(
      input({files: files({filename: 'frontend/old.ts', status: 'removed', sha: 'base-v2'})}),
      api({filesAt: async () => files({filename: 'frontend/old.ts', status: 'removed', sha: 'base-v1'})})
    )

    expect(decision).toMatchObject({reuse: true})
  })

  test.each<[string, Partial<ReuseInput>, Partial<ReuseApi>, string]>([
    ['a scoped input has new content', {files: files({...appFile, sha: 'app-v2'})}, {}, 'inputs-changed'],
    [
      'a scoped input is added',
      {files: files(appFile, {filename: 'frontend/src/new.ts', status: 'added', sha: 'new-v1'})},
      {},
      'inputs-changed'
    ],
    [
      'a scoped input left the pull request',
      {},
      {filesAt: async () => files(appFile, {filename: 'frontend/src/gone.ts', status: 'modified', sha: 'gone-v1'})},
      'inputs-changed'
    ],
    [
      'a rename moves a scoped input',
      {
        files: files({
          filename: 'frontend/src/moved.ts',
          previous_filename: 'frontend/src/app.ts',
          status: 'renamed',
          sha: 'app-v1'
        })
      },
      {},
      'inputs-changed'
    ],
    [
      'the previous gate failed',
      {},
      {checkRuns: async () => [{...green, conclusion: 'failure'}]},
      'previous-not-green'
    ],
    [
      'the previous gate is still running',
      {},
      {checkRuns: async () => [{status: 'in_progress', conclusion: null, startedAt: green.startedAt}]},
      'previous-not-green'
    ],
    [
      'one of several previous gate runs was cancelled',
      {},
      {checkRuns: async () => [green, {...green, conclusion: 'cancelled'}]},
      'previous-not-green'
    ],
    ['the previous head has no gate run', {}, {checkRuns: async () => []}, 'previous-not-green'],
    [
      'the previous gate ran before the pull request was marked ready',
      {},
      {checkRuns: async () => [{...green, startedAt: '2026-11-10T11:00:00Z'}]},
      'previous-ran-as-draft'
    ],
    ['the event is not a push', {action: 'ready_for_review'}, {}, 'not-a-push'],
    [
      'the pull request comes from a fork',
      {pr: pullRequest({head: {sha: 'c'.repeat(40), ref: 'feature', repo: {full_name: 'someone/posthog'}}})},
      {},
      'fork'
    ],
    [
      'the head is a merge queue branch',
      {
        pr: pullRequest({
          head: {sha: 'c'.repeat(40), ref: 'trunk-merge/pr-7/abc', repo: {full_name: 'PostHog/posthog'}}
        })
      },
      {},
      'merge-queue'
    ],
    ['a label forces the full run', {pr: pullRequest({labels: [{name: 'run-ci-frontend'}]})}, {}, 'blocking-label'],
    ['the push has no previous head', {before: '0'.repeat(40)}, {}, 'no-previous-head'],
    ['the current file list is truncated', {truncated: true}, {}, 'file-list-truncated'],
    ['the previous file list is truncated', {}, {filesAt: async () => null}, 'file-list-truncated'],
    ['no scoped input is in the pull request', {files: files(backendFile)}, {}, 'no-inputs'],
    ['reuse is switched off', {config: {...config, disabled: true}}, {}, 'disabled'],
    [
      'the GitHub API fails',
      {},
      {
        checkRuns: async () => {
          throw new Error('503')
        }
      },
      'error'
    ]
  ])('does not reuse when %s', async (_, inputOverrides, apiOverrides, reason) => {
    const decision = await evaluate(input(inputOverrides), api(apiOverrides))

    expect(decision).toMatchObject({reuse: false, reason, previousSha: null})
  })

  test('a previous job that was skipped counts as passing', async () => {
    const decision = await evaluate(input(), api({checkRuns: async () => [{...green, conclusion: 'skipped'}]}))

    expect(decision).toMatchObject({reuse: true})
  })

  test('a draft reuses a gate that ran before any ready-for-review event', async () => {
    const decision = await evaluate(
      input({pr: pullRequest({draft: true})}),
      api({checkRuns: async () => [{...green, startedAt: '2026-11-10T11:00:00Z'}]})
    )

    expect(decision).toMatchObject({reuse: true})
  })

  test('a reused result clears only the scoped filters', () => {
    const results = filter.match(files(appFile, {filename: 'docs/readme.md', status: 'modified', sha: 'doc-v1'}))

    const cleared = withoutReusedKeys(results, ['frontend'])

    expect(cleared.frontend).toEqual([])
    expect(cleared.docs.map(file => file.filename)).toEqual(['docs/readme.md'])
  })

  test('a scope that names an unknown filter fails the action', () => {
    jest
      .mocked(core.getInput)
      .mockImplementation(name => ({'reuse-checks': GATE, 'reuse-filters': 'frontend, fronted'}[name] ?? ''))

    expect(() => loadConfig(filter)).toThrow('fronted')
  })
})
