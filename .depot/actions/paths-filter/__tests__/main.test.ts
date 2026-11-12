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
