// Run with: node --test .github/scripts/ci-fail-fast.test.js

const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const failFast = require('./ci-fail-fast')
const { selectCancellableRuns, parseAllowlist } = failFast

const ALLOW = new Set(['Backend CI', 'Frontend CI', 'Rust CI'])

const makeRun = (over = {}) => ({
    id: 1,
    name: 'Backend CI',
    status: 'in_progress',
    event: 'pull_request',
    ...over,
})

// Minimal call-recording mock (no jest in the node:test runner).
function recordingFn(impl) {
    const fn = (...args) => {
        fn.calls.push(args)
        return impl ? impl(...args) : undefined
    }
    fn.calls = []
    return fn
}

function makeMocks({ runs, mode }) {
    const outputs = {}
    const cancelWorkflowRun = recordingFn(async () => ({}))
    const github = {
        paginate: recordingFn(async () => runs),
        rest: { actions: { listWorkflowRunsForRepo: recordingFn(), cancelWorkflowRun } },
    }
    const summaryChain = {
        addHeading: () => summaryChain,
        addRaw: () => summaryChain,
        write: recordingFn(async () => {}),
    }
    const core = {
        notice: recordingFn(),
        warning: recordingFn(),
        setOutput: recordingFn((k, v) => {
            outputs[k] = v
        }),
        summary: summaryChain,
    }
    const context = {
        repo: { owner: 'PostHog', repo: 'posthog' },
        payload: {
            workflow_run: {
                id: 999,
                name: 'Frontend CI',
                conclusion: 'failure',
                head_sha: 'abcdef1234567890',
                event: 'pull_request',
                pull_requests: [{ number: 42 }],
            },
        },
    }
    process.env.CI_FAIL_FAST_MODE = mode
    process.env.CI_FAIL_FAST_ALLOWLIST = JSON.stringify([...ALLOW])
    return { github, core, context, outputs, cancelWorkflowRun }
}

// Wire up mocks, run the action, hand back the mock bag for assertions.
async function runFailFast(opts) {
    const m = makeMocks(opts)
    await failFast({ github: m.github, context: m.context, core: m.core })
    return m
}

describe('ci-fail-fast', () => {
    describe('parseAllowlist', () => {
        it('returns an empty set for missing input', () => {
            assert.equal(parseAllowlist(undefined).size, 0)
            assert.equal(parseAllowlist('').size, 0)
        })

        it('parses, trims, and drops blanks', () => {
            const set = parseAllowlist('[" Backend CI ", "Rust CI", ""]')
            assert.deepEqual([...set], ['Backend CI', 'Rust CI'])
        })
    })

    describe('selectCancellableRuns', () => {
        const cases = [
            ['keeps an active, allowlisted PR run', makeRun(), true],
            ['drops the source run itself', makeRun({ id: 999 }), false, 999],
            ['drops finished runs', makeRun({ status: 'completed' }), false],
            ['drops non-PR runs (push sharing the SHA)', makeRun({ event: 'push' }), false],
            ['drops workflows not on the allowlist', makeRun({ name: 'Container Images CD' }), false],
            ['keeps queued runs', makeRun({ status: 'queued' }), true],
        ]

        for (const [title, run, expected, sourceRunId = 999] of cases) {
            it(title, () => {
                const got = selectCancellableRuns({ runs: [run], sourceRunId, allow: ALLOW })
                assert.equal(got.length === 1, expected)
            })
        }

        it('filters a mixed batch down to the cancellable runs', () => {
            const runs = [
                makeRun({ id: 1, name: 'Backend CI' }),
                makeRun({ id: 2, name: 'Rust CI', status: 'queued' }),
                makeRun({ id: 3, name: 'Deploy', event: 'pull_request' }), // not allowlisted
                makeRun({ id: 4, name: 'Backend CI', status: 'completed' }), // finished
                makeRun({ id: 999, name: 'Frontend CI' }), // source
            ]
            const got = selectCancellableRuns({ runs, sourceRunId: 999, allow: ALLOW })
            assert.deepEqual(
                got.map((r) => r.id),
                [1, 2]
            )
        })
    })

    describe('run()', () => {
        const siblings = [
            makeRun({ id: 1, name: 'Backend CI' }),
            makeRun({ id: 2, name: 'Rust CI', status: 'queued' }),
            makeRun({ id: 999, name: 'Frontend CI' }), // source, excluded
        ]

        it('dry mode cancels nothing but reports the count', async () => {
            const { outputs, cancelWorkflowRun } = await runFailFast({ runs: siblings, mode: 'dry' })
            assert.equal(cancelWorkflowRun.calls.length, 0)
            assert.equal(outputs.mode, 'dry')
            assert.equal(outputs.count, '2')
            assert.match(outputs.summary, /Would cancel 2 sibling/)
        })

        it('on mode cancels each sibling run', async () => {
            const { outputs, cancelWorkflowRun } = await runFailFast({ runs: siblings, mode: 'on' })
            assert.equal(cancelWorkflowRun.calls.length, 2)
            assert.deepEqual(
                cancelWorkflowRun.calls.map((c) => c[0].run_id).sort(),
                [1, 2]
            )
            assert.equal(outputs.count, '2')
        })

        it('emits an empty summary output when nothing is in flight', async () => {
            const { outputs } = await runFailFast({ runs: [siblings[2]], mode: 'on' })
            assert.equal(outputs.count, '0')
            assert.equal(outputs.summary, '')
        })

        it('swallows a cancel error without throwing', async () => {
            const { github, core, context } = makeMocks({ runs: siblings, mode: 'on' })
            github.rest.actions.cancelWorkflowRun = recordingFn(async () => {
                throw new Error('409 already cancelled')
            })
            await failFast({ github, context, core })
            assert.equal(core.warning.calls.length, 2)
        })
    })
})
