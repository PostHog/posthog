import * as core from '@actions/core'
import * as github from '@actions/github'
import * as git from '../src/git'
import {ChangeStatus} from '../src/file'

jest.mock('@actions/core')
jest.mock('@actions/github', () => ({
  context: {eventName: 'push', payload: {}, ref: 'refs/heads/master', repo: {owner: 'example', repo: 'example'}},
  getOctokit: jest.fn()
}))
jest.mock('../src/git')
jest.mock('../src/shadow', () => ({report: jest.fn()}))

describe('filename log output', () => {
  test.each(['push', 'pull_request'])('%s logs filenames on one line', async eventName => {
    const filename = 'line\n::notice::filename\r.txt'
    const logs: string[] = []
    const completed = new Promise<void>((resolve, reject) => {
      jest.mocked(core.setOutput).mockImplementation(name => {
        if (name === 'changes') resolve()
      })
      jest.mocked(core.setFailed).mockImplementation(message => reject(new Error(String(message))))
    })
    jest
      .mocked(core.getInput)
      .mockImplementation(name => ({filters: JSON.stringify({files: [filename]}), token: 'test-token'}[name] ?? ''))
    jest.mocked(core.info).mockImplementation(message => {
      logs.push(message)
    })
    github.context.eventName = eventName
    github.context.payload = {
      repository: {name: 'example', owner: {login: 'example'}, default_branch: 'master'},
      pull_request: {number: 1}
    }
    jest.mocked(git.getShortName).mockImplementation(ref => ref.replace('refs/heads/', ''))
    jest.mocked(git.getCurrentRef).mockResolvedValue('master')
    jest.mocked(git.getChangesInLastCommit).mockResolvedValue([{filename, status: ChangeStatus.Added}])
    jest.mocked(github.getOctokit).mockReturnValue({
      rest: {pulls: {listFiles: {endpoint: {merge: () => ({})}}}},
      paginate: {
        iterator: async function* () {
          yield {status: 200, data: [{filename, status: 'added'}]}
        }
      }
    } as unknown as ReturnType<typeof github.getOctokit>)
    jest.isolateModules(() => {
      require('../src/main')
    })
    await completed
    expect(logs.filter(line => line.includes('filename'))).toEqual(
      eventName === 'pull_request'
        ? [`[added] ${JSON.stringify(filename)}`, `${JSON.stringify(filename)} [added]`]
        : [`${JSON.stringify(filename)} [added]`]
    )
    expect(logs.join('\n')).not.toMatch(/(?:^|[\r\n])::notice::filename/)
  })
})

describe('reuse wiring', () => {
  test('a reused result reports the scoped filter as unchanged', async () => {
    const outputs: Record<string, unknown> = {}
    const completed = new Promise<void>((resolve, reject) => {
      jest.mocked(core.setOutput).mockImplementation((name, value) => {
        outputs[name] = value
        if (name === 'reused_from') resolve()
      })
      jest.mocked(core.setFailed).mockImplementation(message => reject(new Error(String(message))))
    })
    jest.mocked(core.getInput).mockImplementation(
      name =>
        ({
          filters: JSON.stringify({app: ['src/**'], docs: ['docs/**']}),
          token: 'test-token',
          'reuse-checks': 'Tests Pass',
          'reuse-proof-checks': 'Tests',
          'reuse-filter-source': '.github/workflows/ci.yml',
          'reuse-filters': 'app'
        }[name] ?? '')
    )
    Object.defineProperty(core, 'summary', {value: {addRaw: () => ({write: async () => undefined})}})
    const previousHead = 'a'.repeat(40)
    const rows = [
      {filename: 'src/app.ts', status: 'modified', sha: 'app-v1'},
      {filename: 'docs/guide.md', status: 'modified', sha: 'guide-v2'}
    ]
    github.context.eventName = 'pull_request'
    github.context.payload = {
      action: 'synchronize',
      before: previousHead,
      repository: {name: 'example', owner: {login: 'example'}, default_branch: 'master'},
      pull_request: {
        number: 1,
        draft: true,
        labels: [],
        head: {sha: 'c'.repeat(40), ref: 'feature', repo: {full_name: 'example/example'}},
        base: {sha: 'b'.repeat(40), ref: 'master', repo: {full_name: 'example/example'}}
      }
    }
    jest.mocked(github.getOctokit).mockReturnValue({
      rest: {
        pulls: {listFiles: {endpoint: {merge: () => ({})}}},
        repos: {
          compareCommitsWithBasehead: async () => ({data: {files: [rows[0]]}}),
          listCommits: async () => ({data: []}),
          listActivities: async () => ({data: [{after: 'c'.repeat(40)}, {after: previousHead}]}),
          listPullRequestsAssociatedWithCommit: async () => ({data: [{number: 1}]})
        },
        checks: {
          listForRef: async () => ({
            data: {
              check_runs: [
                {status: 'completed', conclusion: 'success', app: {slug: 'github-actions'}, check_suite: {id: 1}}
              ]
            }
          }),
          listSuitesForRef: 'listSuitesForRef'
        }
      },
      paginate: Object.assign(async () => [{id: 1, created_at: new Date(Date.now() - 60_000).toISOString()}], {
        iterator: async function* () {
          yield {status: 200, data: rows}
        }
      }),
      graphql: async (query: string) =>
        query.includes('timelineItems')
          ? {repository: {pullRequest: {timelineItems: {nodes: []}}}}
          : {repository: {t0: {entries: [{name: 'app.ts', mode: 33188}]}}}
    } as unknown as ReturnType<typeof github.getOctokit>)
    jest.isolateModules(() => {
      require('../src/main')
    })
    await completed

    expect(outputs).toMatchObject({app: false, app_count: 0, docs: true, reused: true, reused_from: previousHead})
  })
})
