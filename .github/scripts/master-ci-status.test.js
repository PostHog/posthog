const fs = require('fs')

jest.mock('fs')

const masterCiStatus = require('./master-ci-status')

const STATE_FILE = '.master-ci-incident'

// Timestamps for testing (in order: T1 < T2 < T3 < T4)
const T1 = 1700000000000 // oldest
const T2 = 1700001000000
const T3 = 1700002000000
const T4 = 1700003000000 // newest

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
        repo: { owner: 'PostHog', repo: 'posthog' },
        payload: {
            workflow_run: {
                name,
                conclusion,
                head_sha: headSha,
            },
        },
    }
}

function createGithubMock(commitTs) {
    return {
        rest: {
            repos: {
                getCommit: jest.fn().mockResolvedValue({
                    data: {
                        commit: {
                            committer: { date: new Date(commitTs).toISOString() },
                        },
                    },
                }),
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
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'failure', 'abc1234')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('create')
            expect(outputs.failing_workflows).toBe('Backend CI')
            expect(outputs.failing_count).toBe('1')
            expect(outputs.commit_count).toBe('1')
            expect(outputs.save_cache).toBe('true')
            expect(outputs.delete_old_caches).toBe('true')

            // Verify state was written with timestamps
            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.fail_ts['Backend CI']).toBe(T1)
            expect(writtenState.sha_ts['abc1234']).toBe(T1)
        })

        it('creates incident on timed_out', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'timed_out', 'abc1234')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('create')
            expect(outputs.failing_workflows).toBe('Backend CI')
        })

        it('does nothing on success with no incident', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'success', 'abc1234')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.save_cache).toBe('false')
        })

        it('ignores cancelled workflows', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'cancelled', 'abc1234')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.save_cache).toBe('false')
        })

        it('ignores skipped workflows', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'skipped', 'abc1234')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.save_cache).toBe('false')
        })
    })

    describe('existing incident', () => {
        const existingState = {
            channel: 'C123',
            ts: '123.456',
            since: '2025-01-01T00:00:00Z',
            sha_ts: { abc1234: T1 },
            fail_ts: { 'Backend CI': T1 },
            ok_ts: {},
        }

        beforeEach(() => {
            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(existingState))
        })

        it('updates on second failure (same workflow, newer commit)', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T2) // Newer commit
            const context = createContext('Backend CI', 'failure', 'def5678')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('update')
            expect(outputs.failing_workflows).toBe('Backend CI')
            expect(outputs.failing_count).toBe('1')
            expect(outputs.commit_count).toBe('2')
            expect(outputs.delete_old_caches).toBe('false') // Only delete on create

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.fail_ts['Backend CI']).toBe(T2) // Updated to newer
        })

        it('updates on failure of different workflow', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T2)
            const context = createContext('Frontend CI', 'failure', 'def5678')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('update')
            expect(outputs.failing_workflows).toContain('Backend CI')
            expect(outputs.failing_workflows).toContain('Frontend CI')
            expect(outputs.failing_count).toBe('2')
        })

        it('does not resolve when different workflow succeeds', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T2)
            const context = createContext('Frontend CI', 'success', 'def5678')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('none')
            expect(outputs.resolved).toBe('false')
            expect(outputs.still_failing).toBe('Backend CI')
            expect(outputs.save_cache).toBe('false') // Don't save on 'none' to prevent divergent branches
        })

        it('resolves when failing workflow succeeds on newer commit', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T2) // Newer than T1
            const context = createContext('Backend CI', 'success', 'def5678')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('resolve')
            expect(outputs.resolved).toBe('true')
            expect(outputs.still_failing).toBe('')
            expect(outputs.save_cache).toBe('true') // Save to persist resolved state
        })

        it('does NOT resolve when failing workflow succeeds on older commit', async () => {
            // State: Backend CI failed at T2
            fs.readFileSync.mockReturnValue(
                JSON.stringify({
                    ...existingState,
                    fail_ts: { 'Backend CI': T2 },
                })
            )

            const { core, outputs } = createMocks()
            const github = createGithubMock(T1) // Older than T2
            const context = createContext('Backend CI', 'success', 'older123')

            await masterCiStatus({ github, context, core })

            // T1 < T2, so ok_ts (T1) is not > fail_ts (T2), still failing
            expect(outputs.action).toBe('none')
            expect(outputs.resolved).toBe('false')
            expect(outputs.still_failing).toBe('Backend CI')
        })

        it('does not resolve when success is on same timestamp as failure', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T1) // Same as fail timestamp
            const context = createContext('Backend CI', 'success', 'abc1234')

            await masterCiStatus({ github, context, core })

            // Success must be strictly newer than failure to count as recovery
            expect(outputs.action).toBe('none')
        })
    })

    describe('multiple workflows failing', () => {
        const multiFailState = {
            channel: 'C123',
            ts: '123.456',
            since: '2025-01-01T00:00:00Z',
            sha_ts: { abc1234: T1, def5678: T2 },
            fail_ts: { 'Backend CI': T1, 'Frontend CI': T2 },
            ok_ts: {},
        }

        beforeEach(() => {
            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(multiFailState))
        })

        it('clears one workflow but not the other', async () => {
            const { core, outputs } = createMocks()
            const github = createGithubMock(T3) // Newer than both T1 and T2
            const context = createContext('Backend CI', 'success', 'ghi9012')

            await masterCiStatus({ github, context, core })

            // Backend CI recovered, but Frontend CI still failing
            expect(outputs.action).toBe('resolve')
            expect(outputs.recovered_workflow).toBe('Backend CI')
            expect(outputs.resolved).toBe('false')
            expect(outputs.still_failing).toBe('Frontend CI')
        })

        it('resolves when all workflows cleared', async () => {
            // Backend CI already cleared
            fs.readFileSync.mockReturnValue(
                JSON.stringify({
                    ...multiFailState,
                    ok_ts: { 'Backend CI': T3 },
                })
            )

            const { core, outputs } = createMocks()
            const github = createGithubMock(T4) // Newer than T2
            const context = createContext('Frontend CI', 'success', 'jkl3456')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('resolve')
            expect(outputs.resolved).toBe('true')
        })
    })

    describe('out-of-order events (timestamp-based)', () => {
        it('older failure does not overwrite newer failure timestamp', async () => {
            const stateWithNewerFailure = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                sha_ts: { abc1234: T1, def5678: T2 },
                fail_ts: { 'Backend CI': T2 }, // Failed at T2
                ok_ts: {},
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(stateWithNewerFailure))

            const { core } = createMocks()
            const github = createGithubMock(T1) // Older commit
            const context = createContext('Backend CI', 'failure', 'abc1234')

            await masterCiStatus({ github, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.fail_ts['Backend CI']).toBe(T2) // Still T2, not T1
        })

        it('older success does not overwrite newer success timestamp', async () => {
            const stateWithNewerSuccess = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                sha_ts: { abc1234: T1, def5678: T2, ghi9012: T3 },
                fail_ts: { 'Backend CI': T1 },
                ok_ts: { 'Backend CI': T3 }, // Succeeded at T3
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(stateWithNewerSuccess))

            const { core } = createMocks()
            const github = createGithubMock(T2) // Older than T3
            const context = createContext('Backend CI', 'success', 'def5678')

            await masterCiStatus({ github, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.ok_ts['Backend CI']).toBe(T3) // Still T3, not T2
        })

        it('newer success clears older failure', async () => {
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                sha_ts: { abc1234: T1 },
                fail_ts: { 'Backend CI': T1 },
                ok_ts: {},
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core, outputs } = createMocks()
            const github = createGithubMock(T2) // Newer than T1
            const context = createContext('Backend CI', 'success', 'def5678')

            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('resolve')
            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.ok_ts['Backend CI']).toBe(T2)
        })
    })

    describe('state validation', () => {
        it('handles missing fields gracefully', async () => {
            // Old format or corrupted state
            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(
                JSON.stringify({
                    channel: 'C123',
                    ts: '123.456',
                    since: '2025-01-01T00:00:00Z',
                    // Missing sha_ts, fail_ts, ok_ts
                })
            )

            const { core, outputs } = createMocks()
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'success', 'abc1234')

            // Should not throw
            await masterCiStatus({ github, context, core })

            // No failures tracked, so nothing to recover from
            expect(outputs.action).toBe('none')
            expect(outputs.resolved).toBe('true') // No failures = resolved
        })

        it('handles JSON parse error', async () => {
            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue('not valid json')

            const { core, outputs } = createMocks()
            const github = createGithubMock(T1)
            const context = createContext('Backend CI', 'failure', 'abc1234')

            // Should not throw, treat as new incident
            await masterCiStatus({ github, context, core })

            expect(outputs.action).toBe('create')
        })
    })

    describe('state pruning', () => {
        it('prunes old SHAs after success clears them', async () => {
            // State with multiple SHAs and one workflow with ok_ts
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                sha_ts: { sha1: T1, sha2: T2, sha3: T3 },
                fail_ts: { 'Backend CI': T3 },
                ok_ts: { 'Frontend CI': T2 }, // Frontend passed at T2
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core } = createMocks()
            const github = createGithubMock(T4)
            const context = createContext('Backend CI', 'success', 'sha4')

            await masterCiStatus({ github, context, core })

            // After Backend CI succeeds at T4, ok_ts has Frontend CI: T2, Backend CI: T4
            // min(ok_ts) = T2, so sha1 (T1 < T2) should be pruned
            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.sha_ts.sha1).toBeUndefined() // Pruned (T1 < T2)
            expect(writtenState.sha_ts.sha2).toBe(T2) // Kept (T2 >= T2)
            expect(writtenState.sha_ts.sha3).toBe(T3) // Kept (T3 > T2)
            expect(writtenState.sha_ts.sha4).toBe(T4) // New SHA added
        })

        it('does not prune when no ok_ts exists', async () => {
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: '2025-01-01T00:00:00Z',
                sha_ts: { sha1: T1, sha2: T2 },
                fail_ts: { 'Backend CI': T2 },
                ok_ts: {},
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core } = createMocks()
            const github = createGithubMock(T3)
            const context = createContext('Frontend CI', 'failure', 'sha3')

            await masterCiStatus({ github, context, core })

            const writtenState = JSON.parse(fs.writeFileSync.mock.calls[0][1])
            expect(writtenState.sha_ts.sha1).toBe(T1) // Still there
            expect(writtenState.sha_ts.sha2).toBe(T2) // Still there
            expect(writtenState.sha_ts.sha3).toBe(T3) // New SHA added
        })
    })

    describe('required workflows check', () => {
        // Use T1 as incident start so T2/T3/T4 are all after it
        const incidentStartTs = T1
        const incidentStart = new Date(incidentStartTs).toISOString()

        beforeEach(() => {
            process.env.REQUIRED_WORKFLOWS = 'Backend CI,Frontend CI'
        })

        afterEach(() => {
            delete process.env.REQUIRED_WORKFLOWS
        })

        it('does not fully resolve if required workflow has not passed since incident', async () => {
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: incidentStart,
                sha_ts: { abc: T2 },
                fail_ts: { 'Backend CI': T2 },
                ok_ts: { 'Frontend CI': T1 - 1000 }, // Passed BEFORE incident
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core, outputs } = createMocks()
            const github = createGithubMock(T4)
            const context = createContext('Backend CI', 'success', 'sha4')

            await masterCiStatus({ github, context, core })

            // Backend CI recovered, but Frontend CI hasn't passed since incident
            expect(outputs.action).toBe('resolve')
            expect(outputs.resolved).toBe('false') // Not fully resolved
        })

        it('fully resolves when all required workflows passed since incident', async () => {
            const state = {
                channel: 'C123',
                ts: '123.456',
                since: incidentStart,
                sha_ts: { abc: T2 },
                fail_ts: { 'Backend CI': T2 },
                ok_ts: { 'Frontend CI': T3 }, // Passed AFTER incident (T3 > T1)
            }

            fs.existsSync.mockReturnValue(true)
            fs.readFileSync.mockReturnValue(JSON.stringify(state))

            const { core, outputs } = createMocks()
            const github = createGithubMock(T4)
            const context = createContext('Backend CI', 'success', 'sha4')

            await masterCiStatus({ github, context, core })

            // Both required workflows have passed since incident
            expect(outputs.action).toBe('resolve')
            expect(outputs.resolved).toBe('true')
        })
    })
})
