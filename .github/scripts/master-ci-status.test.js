const fs = require('fs')

jest.mock('fs')

const masterCiStatus = require('./master-ci-status')

const STATE_FILE = '.master-ci-incident'

function createMocks() {
    const outputs = {}
    const core = {
        setOutput: jest.fn((key, value) => {
            outputs[key] = value
        }),
    }
    return { core, outputs }
}

function createContext(name, conclusion, headSha) {
    return {
        payload: {
            workflow_run: {
                name,
                conclusion,
                head_sha: headSha,
            },
        },
    }
}

describe('master-ci-status', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        fs.existsSync.mockReturnValue(false)
        fs.readFileSync.mockReturnValue('{}')
        fs.writeFileSync.mockImplementation(() => {})
    })

    describe('new incident (no existing state)', () => {
        it('creates incident on first failure', async () => {
            const { core, outputs } = createMocks()
            const context = createContext('Backend CI', 'failure', 'abc1234')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('create')
            expect(outputs.failing_workflows).toBe('Backend CI')
            expect(outputs.failing_count).toBe('1')
            expect(outputs.commit_count).toBe('1')
            expect(outputs.save_cache).toBe('true')

            // Verify state was written
            expect(fs.writeFileSync).toHaveBeenCalledWith(
                STATE_FILE,
                expect.stringContaining('"fail_seq"')
            )
        })

        it('does nothing on success with no incident', async () => {
            const { core, outputs } = createMocks()
            const context = createContext('Backend CI', 'success', 'abc1234')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.save_cache).toBe('false')
        })
    })

    describe('existing incident', () => {
        const existingState = {
            channel: 'C123',
            ts: '123.456',
            since: '2025-01-01T00:00:00Z',
            commits: ['abc1234'],
            fail_seq: { 'Backend CI': 0 },
            ok_seq: {},
        }

        beforeEach(() => {
            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(existingState))
        })

        it('updates on second failure (same workflow, new commit)', async () => {
            const { core, outputs } = createMocks()
            const context = createContext('Backend CI', 'failure', 'def5678')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('update')
            expect(outputs.failing_workflows).toBe('Backend CI')
            expect(outputs.failing_count).toBe('1')
            expect(outputs.commit_count).toBe('2')
        })

        it('updates on failure of different workflow', async () => {
            const { core, outputs } = createMocks()
            const context = createContext('Frontend CI', 'failure', 'def5678')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('update')
            expect(outputs.failing_workflows).toContain('Backend CI')
            expect(outputs.failing_workflows).toContain('Frontend CI')
            expect(outputs.failing_count).toBe('2')
        })

        it('does not resolve when different workflow succeeds', async () => {
            const { core, outputs } = createMocks()
            const context = createContext('Frontend CI', 'success', 'def5678')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.resolved).toBe('false')
            expect(outputs.still_failing).toBe('Backend CI')
        })

        it('resolves when failing workflow succeeds on newer commit', async () => {
            const { core, outputs } = createMocks()
            const context = createContext('Backend CI', 'success', 'def5678')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('resolve')
            expect(outputs.resolved).toBe('true')
            expect(outputs.still_failing).toBe('')
            expect(outputs.save_cache).toBe('false')
        })

        it('does not resolve when failing workflow succeeds on same commit', async () => {
            // Same commit order (0) - ok_seq would equal fail_seq, not greater
            const { core, outputs } = createMocks()
            const context = createContext('Backend CI', 'success', 'abc1234')

            await masterCiStatus({ github: {}, context, core })

            // ok_seq[Backend CI] = 0, fail_seq[Backend CI] = 0
            // 0 > 0 is false, so not failing anymore
            expect(outputs.action).toBe('resolve')
        })
    })

    describe('multiple workflows failing', () => {
        const multiFailState = {
            channel: 'C123',
            ts: '123.456',
            since: '2025-01-01T00:00:00Z',
            commits: ['abc1234', 'def5678'],
            fail_seq: { 'Backend CI': 0, 'Frontend CI': 1 },
            ok_seq: {},
        }

        beforeEach(() => {
            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(multiFailState))
        })

        it('clears one workflow but not the other', async () => {
            const { core, outputs } = createMocks()
            // New commit (order 2) succeeds for Backend CI
            const context = createContext('Backend CI', 'success', 'ghi9012')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.resolved).toBe('false')
            expect(outputs.still_failing).toBe('Frontend CI')
        })

        it('resolves when all workflows cleared', async () => {
            // First clear Backend CI
            fs.readFileSync.mockReturnValue(
                JSON.stringify({
                    ...multiFailState,
                    commits: ['abc1234', 'def5678', 'ghi9012'],
                    ok_seq: { 'Backend CI': 2 },
                })
            )

            const { core, outputs } = createMocks()
            // Now clear Frontend CI
            const context = createContext('Frontend CI', 'success', 'jkl3456')

            await masterCiStatus({ github: {}, context, core })

            expect(outputs.action).toBe('resolve')
            expect(outputs.resolved).toBe('true')
        })
    })

    describe('out-of-order events', () => {
        it('uses max() for fail_seq - older failure does not overwrite newer', async () => {
            const stateWithNewerFailure = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                commits: ['abc1234', 'def5678'],
                fail_seq: { 'Backend CI': 1 }, // Failed on commit index 1
                ok_seq: {},
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(stateWithNewerFailure))

            const { core } = createMocks()
            // Older commit (index 0) also fails - should not overwrite
            const context = createContext('Backend CI', 'failure', 'abc1234')

            await masterCiStatus({ github: {}, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.fail_seq['Backend CI']).toBe(1) // Still 1, not 0
        })

        it('uses max() for ok_seq - older success does not overwrite newer', async () => {
            const stateWithNewerSuccess = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                commits: ['abc1234', 'def5678', 'ghi9012'],
                fail_seq: { 'Backend CI': 0 },
                ok_seq: { 'Backend CI': 2 }, // Succeeded on commit index 2
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(stateWithNewerSuccess))

            const { core } = createMocks()
            // Older commit (index 1) also succeeds - should not overwrite
            const context = createContext('Backend CI', 'success', 'def5678')

            await masterCiStatus({ github: {}, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.ok_seq['Backend CI']).toBe(2) // Still 2, not 1
        })
    })

    describe('commit ordering', () => {
        it('assigns correct order to new commits', async () => {
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                commits: ['abc1234', 'def5678'],
                fail_seq: { 'Backend CI': 0 },
                ok_seq: {},
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core } = createMocks()
            const context = createContext('Backend CI', 'success', 'ghi9012') // New commit

            await masterCiStatus({ github: {}, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.commits).toContain('ghi9012')
            expect(writtenState.commits.indexOf('ghi9012')).toBe(2)
            expect(writtenState.ok_seq['Backend CI']).toBe(2)
        })

        it('reuses order for existing commits', async () => {
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                commits: ['abc1234', 'def5678'],
                fail_seq: { 'Backend CI': 0 },
                ok_seq: {},
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core } = createMocks()
            const context = createContext('Frontend CI', 'success', 'def5678') // Existing commit

            await masterCiStatus({ github: {}, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.commits.length).toBe(2) // No new commit added
            expect(writtenState.ok_seq['Frontend CI']).toBe(1) // Order of def5678
        })
    })
})
