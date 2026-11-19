import * as core from '@actions/core'
import * as github from '@actions/github'
import {PullRequest} from '@octokit/webhooks-types'

import {ApiFileRow, File, filesFromApiRow} from '../src/file'
import {Filter} from '../src/filter'
import {
  CheckRun,
  ReuseApi,
  ReuseConfig,
  ReuseInput,
  evaluate,
  githubApi,
  loadConfig,
  withoutReusedKeys
} from '../src/reuse'

jest.mock('@actions/core')
jest.mock('@actions/github', () => ({context: {repo: {owner: 'PostHog', repo: 'posthog'}}, getOctokit: jest.fn()}))

const CURRENT_HEAD = 'c'.repeat(40)
const PREVIOUS_HEAD = 'a'.repeat(40)
const EARLIER_HEAD = 'd'.repeat(40)
const BASE = 'b'.repeat(40)
const READY_AT = '2026-11-10T12:00:00Z'
const NOW = Date.parse('2026-11-10T14:00:00Z')
const GATE = 'Frontend Tests Pass'
const PROOF = 'Frontend formatting'
const WORKFLOW = '.github/workflows/ci-frontend.yml'

const filter = new Filter(`
frontend:
  - 'frontend/**'
docs:
  - 'docs/**'
`)

const config: ReuseConfig = {
  checks: [GATE],
  proofChecks: [PROOF],
  checkApps: ['github-actions'],
  filterSource: WORKFLOW,
  keys: ['frontend'],
  blockingLabels: ['run-ci-frontend'],
  disabled: false
}

const green: CheckRun = {
  status: 'completed',
  conclusion: 'success',
  app: 'github-actions',
  suiteCreatedAt: '2026-11-10T13:00:00Z'
}
const skipped: CheckRun = {...green, conclusion: 'skipped'}

function runsByHead(heads: Record<string, Record<string, CheckRun[]>>): ReuseApi['checkRuns'] {
  return async (sha, name) => heads[sha]?.[name] ?? []
}

function files(...rows: ApiFileRow[]): File[] {
  return rows.flatMap(filesFromApiRow)
}

const appFile: ApiFileRow = {filename: 'frontend/src/app.ts', status: 'modified', sha: 'app-v1'}
const backendFile: ApiFileRow = {filename: 'posthog/api.py', status: 'modified', sha: 'api-v1'}

function pullRequest(overrides: Record<string, unknown> = {}): PullRequest {
  return {
    number: 7,
    draft: false,
    created_at: '2026-11-10T10:00:00Z',
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
    runAttempt: 1,
    now: NOW,
    pr: pullRequest(),
    ...overrides
  }
}

function api(overrides: Partial<ReuseApi> = {}): () => ReuseApi {
  return () => ({
    filesAt: async () => files(appFile),
    checkRuns: async () => [green],
    modes: async (_, paths) => new Map(paths.map(path => [path, 33188])),
    branchHeads: async () => [CURRENT_HEAD, PREVIOUS_HEAD, EARLIER_HEAD],
    blobs: async (shas, paths) => new Map(shas.map(sha => [sha, paths.map(() => 'blob')])),
    pullsWithCommit: async () => [7],
    timeline: async () => ({readyForReviewAt: READY_AT, baseChangedAt: null}),
    changedOnBranchSince: async () => false,
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
      'no head finished the suite',
      {},
      {checkRuns: async () => [{...green, status: 'in_progress', conclusion: null}]},
      'no-proven-run'
    ],
    [
      'one of several gate runs was cancelled on every head',
      {},
      {checkRuns: async () => [green, {...green, conclusion: 'cancelled'}]},
      'no-proven-run'
    ],
    ['no head has a gate run', {}, {checkRuns: async () => []}, 'no-proven-run'],
    [
      'the only green gate came from another App',
      {},
      {checkRuns: async () => [{...green, app: 'some-other-app'}]},
      'no-proven-run'
    ],
    [
      'a scoped input lost its executable bit',
      {},
      {
        modes: async (sha, paths) => new Map(paths.map(path => [path, sha === PREVIOUS_HEAD ? 33261 : 33188]))
      },
      'inputs-changed'
    ],
    [
      'the proven run claims to start in the future',
      {},
      {checkRuns: async () => [{...green, suiteCreatedAt: '2099-01-01T00:00:00Z'}]},
      'error'
    ],
    [
      'the previous gate ran before the pull request was marked ready',
      {},
      {checkRuns: async () => [{...green, suiteCreatedAt: '2026-11-10T11:00:00Z'}]},
      'previous-ran-as-draft'
    ],
    [
      'the previous head passed only because its suite was skipped, and the head before it failed',
      {},
      {
        checkRuns: runsByHead({
          [PREVIOUS_HEAD]: {[GATE]: [green], [PROOF]: [skipped]},
          [EARLIER_HEAD]: {[GATE]: [{...green, conclusion: 'failure'}], [PROOF]: [{...green, conclusion: 'failure'}]}
        })
      },
      'previous-not-green'
    ],
    [
      'no earlier head ran the suite',
      {},
      {
        checkRuns: runsByHead({[PREVIOUS_HEAD]: {[GATE]: [green], [PROOF]: [skipped]}}),
        branchHeads: async () => [CURRENT_HEAD, PREVIOUS_HEAD]
      },
      'no-proven-run'
    ],
    [
      'the head that ran the suite had other inputs',
      {},
      {
        checkRuns: runsByHead({
          [PREVIOUS_HEAD]: {[GATE]: [green], [PROOF]: [skipped]},
          [EARLIER_HEAD]: {[GATE]: [green], [PROOF]: [green]}
        }),
        filesAt: async (_, sha) => (sha === EARLIER_HEAD ? files({...appFile, sha: 'app-v0'}) : files(appFile))
      },
      'no-proven-run'
    ],
    [
      'the pull request changed the filters',
      {files: files(appFile, {filename: WORKFLOW, status: 'modified', sha: 'workflow-v2'})},
      {filesAt: async () => files(appFile, {filename: WORKFLOW, status: 'modified', sha: 'workflow-v1'})},
      'inputs-changed'
    ],
    [
      'the base branch changed the filters after the run',
      {},
      {changedOnBranchSince: async () => true},
      'filter-changed'
    ],
    [
      'the pull request was retargeted after the run',
      {},
      {timeline: async () => ({readyForReviewAt: READY_AT, baseChangedAt: '2026-11-10T13:30:00Z'})},
      'base-changed'
    ],
    ['another pull request shares the head that ran', {}, {pullsWithCommit: async () => [7, 8]}, 'shared-head'],
    [
      'the head ran before the pull request was opened',
      {pr: pullRequest({created_at: '2026-11-10T13:30:00Z'})},
      {},
      'shared-head'
    ],
    ['the run is more than a day old', {now: NOW + 2 * 24 * 60 * 60 * 1000}, {}, 'previous-too-old'],
    ['the workflow is re-run', {runAttempt: 2}, {}, 're-run'],
    ['the file that defines the filters is unknown', {config: {...config, filterSource: null}}, {}, 'error'],
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

  test('a failed lookup aborts the lookups still in flight', async () => {
    let signal: AbortSignal | undefined
    const stalled = new Promise<never>(() => undefined)

    const decision = await evaluate(input(), received => {
      signal = received
      return api({
        checkRuns: async (_, name) => {
          if (name === PROOF) {
            return stalled
          }
          throw new Error('503')
        }
      })()
    })

    expect(decision).toMatchObject({reuse: false, reason: 'error'})
    expect(signal?.aborted).toBe(true)
  })

  test('a skipped gate passes when the suite ran on that head', async () => {
    const decision = await evaluate(
      input(),
      api({checkRuns: runsByHead({[PREVIOUS_HEAD]: {[GATE]: [skipped], [PROOF]: [green]}})})
    )

    expect(decision).toMatchObject({reuse: true, previousSha: PREVIOUS_HEAD})
  })

  test('a chain of reused heads reuses the head where the suite last ran', async () => {
    const decision = await evaluate(
      input(),
      api({
        checkRuns: runsByHead({
          [PREVIOUS_HEAD]: {[GATE]: [green], [PROOF]: [skipped]},
          [EARLIER_HEAD]: {[GATE]: [green], [PROOF]: [green]}
        })
      })
    )

    expect(decision).toMatchObject({reuse: true, previousSha: EARLIER_HEAD})
  })

  test.each<[string, Record<string, CheckRun[]>]>([
    ['failed with other inputs', {[GATE]: [{...green, conclusion: 'failure'}]}],
    ['passed with other inputs', {[GATE]: [green], [PROOF]: [green]}]
  ])(
    'a push that restores the inputs of an earlier green head reuses it when the previous head %s',
    async (_, previousRuns) => {
      const decision = await evaluate(
        input(),
        api({
          filesAt: async (_base, sha) =>
            sha === PREVIOUS_HEAD ? files({...appFile, sha: 'app-broken'}) : files(appFile),
          checkRuns: runsByHead({[PREVIOUS_HEAD]: previousRuns, [EARLIER_HEAD]: {[GATE]: [green], [PROOF]: [green]}})
        })
      )

      expect(decision).toMatchObject({reuse: true, previousSha: EARLIER_HEAD, headsBehind: 1})
    }
  )

  test('an earlier head that cannot be compared stops the search before an older green head', async () => {
    const OLDEST_HEAD = 'e'.repeat(40)

    const decision = await evaluate(
      input(),
      api({
        branchHeads: async () => [CURRENT_HEAD, PREVIOUS_HEAD, EARLIER_HEAD, OLDEST_HEAD],
        filesAt: async (_base, sha) => {
          if (sha === PREVIOUS_HEAD) {
            return files({...appFile, sha: 'app-broken'})
          }
          return sha === EARLIER_HEAD ? null : files(appFile)
        },
        checkRuns: runsByHead({
          [EARLIER_HEAD]: {[GATE]: [{...green, conclusion: 'failure'}]},
          [OLDEST_HEAD]: {[GATE]: [green], [PROOF]: [green]}
        })
      })
    )

    expect(decision).toMatchObject({reuse: false, reason: 'file-list-truncated', detail: EARLIER_HEAD})
  })

  test('a superseded previous head does not stop the search for the head that ran', async () => {
    const decision = await evaluate(
      input(),
      api({
        checkRuns: runsByHead({
          [PREVIOUS_HEAD]: {[GATE]: [{...green, conclusion: 'cancelled'}]},
          [EARLIER_HEAD]: {[GATE]: [green], [PROOF]: [green]}
        })
      })
    )

    expect(decision).toMatchObject({reuse: true, previousSha: EARLIER_HEAD})
  })

  test.each<[string, Partial<ReuseApi>]>([
    [
      'their sampled blobs differ',
      {
        blobs: async (shas, paths) =>
          new Map(shas.map(sha => [sha, paths.map(() => (sha === CURRENT_HEAD ? 'v2' : 'v1'))]))
      }
    ],
    ['an input outside the sampled blobs differs', {}]
  ])('a push that changes an input reads no check runs from heads where %s', async (_, overrides) => {
    const headsRead: string[] = []

    const decision = await evaluate(
      input({files: files({...appFile, sha: 'app-v2'})}),
      api({
        ...overrides,
        checkRuns: async sha => {
          headsRead.push(sha)
          return [green]
        }
      })
    )

    expect(decision).toMatchObject({reuse: false, reason: 'inputs-changed', detail: 'frontend/src/app.ts'})
    expect(headsRead).toEqual([])
  })

  test.each<[string, Partial<ReuseApi>, number | null]>([
    [
      'the branch activity cannot be listed',
      {
        branchHeads: async () => {
          throw new Error('403')
        }
      },
      null
    ],
    [
      'the contents of earlier heads cannot be read',
      {
        blobs: async () => {
          throw new Error('502')
        }
      },
      2
    ]
  ])('the previous head is still reused when %s', async (_, overrides, earlierHeads) => {
    const decision = await evaluate(input(), api(overrides))

    expect(decision).toMatchObject({reuse: true, previousSha: PREVIOUS_HEAD, earlierHeads})
  })

  test('a draft reuses a gate that ran before any ready-for-review event', async () => {
    const decision = await evaluate(
      input({pr: pullRequest({draft: true})}),
      api({checkRuns: async () => [{...green, suiteCreatedAt: '2026-11-10T11:00:00Z'}]})
    )

    expect(decision).toMatchObject({reuse: true})
  })

  test('a reused result clears only the scoped filters', () => {
    const results = filter.match(files(appFile, {filename: 'docs/readme.md', status: 'modified', sha: 'doc-v1'}))

    const cleared = withoutReusedKeys(results, ['frontend'])

    expect(cleared.frontend).toEqual([])
    expect(cleared.docs.map(file => file.filename)).toEqual(['docs/readme.md'])
  })

  test.each<[string, Record<string, string>, string]>([
    ['names an unknown filter', {'reuse-proof-checks': PROOF, 'reuse-filters': 'frontend, fronted'}, 'fronted'],
    ['names no proof check', {}, 'reuse-proof-checks']
  ])('a configuration that %s fails the action', (_, inputs, message) => {
    jest.mocked(core.getInput).mockImplementation(name => ({'reuse-checks': GATE, ...inputs}[name] ?? ''))

    expect(() => loadConfig(filter, null)).toThrow(message)
  })

  describe('the GitHub API adapter', () => {
    const requests: Record<string, Record<string, unknown>> = {}
    const record =
      (name: string, data: unknown) =>
      async (params: Record<string, unknown>): Promise<{data: unknown}> => {
        requests[name] = params
        return {data}
      }

    function adapter(compareRows: number, timelineNodes: {__typename: string; createdAt: string}[] = []): ReuseApi {
      jest.mocked(github.getOctokit).mockReturnValue({
        rest: {
          repos: {
            compareCommitsWithBasehead: record('compare', {
              files: Array.from({length: compareRows}, (_, i) => ({
                filename: `f${i}`,
                status: 'modified',
                sha: `s${i}`
              }))
            }),
            listCommits: record('commits', [{sha: 'x'}]),
            listActivities: record('activity', [
              {after: PREVIOUS_HEAD, activity_type: 'force_push'},
              {after: EARLIER_HEAD, activity_type: 'push'}
            ])
          },
          checks: {
            listForRef: record('checks', {
              check_runs: [
                {status: 'completed', conclusion: 'success', app: {slug: 'github-actions'}, check_suite: {id: 2}}
              ]
            }),
            listSuitesForRef: 'listSuitesForRef'
          }
        },
        paginate: async (method: string, params: Record<string, unknown>) => {
          requests[method] = params
          return [
            {id: 1, created_at: '2026-11-10T12:00:00Z'},
            {id: 2, created_at: '2026-11-10T13:00:00Z'}
          ]
        },
        graphql: async (query: string, variables: Record<string, unknown>) => {
          requests.graphql = variables
          return query.includes('timelineItems')
            ? {repository: {pullRequest: {timelineItems: {nodes: timelineNodes}}}}
            : {
                repository: {
                  t0: {entries: [{name: 'ci-wait', mode: 33261}]},
                  t1: {entries: [{name: 'package.json', mode: 33188}]},
                  b0_0: {oid: 'app-v2'},
                  b0_1: null,
                  b1_0: {oid: 'app-v1'},
                  b1_1: {oid: 'old-v1'}
                }
              }
        }
      } as unknown as ReturnType<typeof github.getOctokit>)
      return githubApi('token', new AbortController().signal)
    }

    test('lists the previous head against the base, and gives up at the 300-file cap', async () => {
      expect(await adapter(299).filesAt(BASE, PREVIOUS_HEAD)).toHaveLength(299)
      expect(requests.compare).toMatchObject({basehead: `${BASE}...${PREVIOUS_HEAD}`})
      expect(await adapter(300).filesAt(BASE, PREVIOUS_HEAD)).toBeNull()
    })

    test('reads only the latest run of each check, with its App and the creation time of its suite', async () => {
      const runs = await adapter(0).checkRuns(PREVIOUS_HEAD, GATE)

      expect(requests.checks).toMatchObject({ref: PREVIOUS_HEAD, check_name: GATE, filter: 'latest'})
      expect(runs).toEqual([
        {status: 'completed', conclusion: 'success', app: 'github-actions', suiteCreatedAt: '2026-11-10T13:00:00Z'}
      ])
    })

    test('reads the Git mode of each path from its directory listing', async () => {
      const modes = await adapter(0).modes(PREVIOUS_HEAD, ['bin/ci-wait', 'package.json', 'bin/gone'])

      expect(requests.graphql).toMatchObject({e0: `${PREVIOUS_HEAD}:bin`, e1: `${PREVIOUS_HEAD}:`})
      expect(modes).toEqual(
        new Map([
          ['bin/ci-wait', 33261],
          ['package.json', 33188],
          ['bin/gone', null]
        ])
      )
    })

    test('lists the heads the branch had in the last day, force pushes included', async () => {
      expect(await adapter(0).branchHeads('feature')).toEqual([PREVIOUS_HEAD, EARLIER_HEAD])
      expect(requests.activity).toMatchObject({ref: 'refs/heads/feature', time_period: 'day'})
    })

    test('reads the blob of each path on each head, and null where the path is absent', async () => {
      const blobs = await adapter(0).blobs([CURRENT_HEAD, PREVIOUS_HEAD], ['frontend/src/app.ts', 'frontend/old.ts'])

      expect(requests.graphql).toMatchObject({
        e0_1: `${CURRENT_HEAD}:frontend/old.ts`,
        e1_0: `${PREVIOUS_HEAD}:frontend/src/app.ts`
      })
      expect(blobs).toEqual(
        new Map([
          [CURRENT_HEAD, ['app-v2', null]],
          [PREVIOUS_HEAD, ['app-v1', 'old-v1']]
        ])
      )
    })

    test('takes the newest ready event and the newest base change of either kind', async () => {
      const timeline = await adapter(0, [
        {__typename: 'ReadyForReviewEvent', createdAt: '2026-11-10T09:00:00Z'},
        {__typename: 'BaseRefForcePushedEvent', createdAt: '2026-11-10T12:00:00Z'},
        {__typename: 'BaseRefChangedEvent', createdAt: '2026-11-10T10:00:00Z'},
        {__typename: 'ReadyForReviewEvent', createdAt: '2026-11-10T11:00:00Z'}
      ]).timeline(7)

      expect(timeline).toEqual({readyForReviewAt: '2026-11-10T11:00:00Z', baseChangedAt: '2026-11-10T12:00:00Z'})
    })

    test('reports a filter change on the base branch since the run', async () => {
      expect(await adapter(0).changedOnBranchSince('master', WORKFLOW, green.suiteCreatedAt as string)).toBe(true)
      expect(requests.commits).toMatchObject({sha: 'master', path: WORKFLOW, since: green.suiteCreatedAt})
    })
  })
})
