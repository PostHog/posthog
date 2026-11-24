// Run with: node --test .github/scripts/backend-full-run-state.test.js

const { test } = require('node:test')
const assert = require('node:assert/strict')
const { fullRunState, FULL_RUN_EXTERNAL_ID, GATE_APP_ID } = require('./backend-full-run-state')

const gateCheck = (conclusion, completedAt, externalId = FULL_RUN_EXTERNAL_ID) => ({
    conclusion,
    externalId,
    completedAt,
})
const commitWith = (...checks) => commitFromApp(GATE_APP_ID, ...checks)
const commitFromApp = (appId, ...checks) => ({
    checkSuites: { nodes: [{ app: { databaseId: appId }, checkRuns: { nodes: checks } }] },
})
const queueEntry = (state, stateChangedAt) => ({ state, stateChangedAt })

const pullRequest = ({ commits = [], replacedHeads = [] }) => ({
    commits: { nodes: commits.map((commit) => ({ commit })) },
    timelineItems: { nodes: replacedHeads.map((beforeCommit) => ({ beforeCommit })) },
})

test('a full run counts as passed only when its gate check succeeded and no queue kick came after it', () => {
    const passed = gateCheck('SUCCESS', '2026-11-10T10:00:00Z')
    const cases = [
        ['no gate check yet', {}, false, false],
        ['a passed full run', { commits: [commitWith(passed)] }, true, false],
        [
            'a passed full run on a head a force-push replaced',
            { replacedHeads: [commitWith(passed), null] },
            true,
            false,
        ],
        [
            'a passed full run whose suite app an app token reads as null',
            { commits: [{ checkSuites: { nodes: [{ app: null, checkRuns: { nodes: [passed] } }] } }] },
            true,
            false,
        ],
        [
            'a passed full run posted by an app other than the gate',
            { commits: [commitFromApp(15368, passed)] },
            false,
            false,
        ],
        [
            'a cancelled full run',
            { commits: [commitWith(gateCheck('CANCELLED', '2026-11-10T10:00:00Z'))] },
            false,
            false,
        ],
        ['a failed full run', { commits: [commitWith(gateCheck('FAILURE', '2026-11-10T10:00:00Z'))] }, false, false],
        [
            'a passed selected run',
            { commits: [commitWith(gateCheck('SUCCESS', '2026-11-10T10:00:00Z', 'backend-matrix=partial'))] },
            false,
            false,
        ],
        [
            'a failed queue attempt after the pass',
            { commits: [commitWith(passed)], queue: queueEntry('FAILED', '2026-11-10T11:00:00Z') },
            false,
            true,
        ],
        [
            'a failed queue attempt after the pass, timed in epoch milliseconds',
            { commits: [commitWith(passed)], queue: queueEntry('FAILED', Date.parse('2026-11-10T11:00:00Z')) },
            false,
            true,
        ],
        [
            'a failed queue attempt before a later pass',
            {
                commits: [commitWith(passed), commitWith(gateCheck('SUCCESS', '2026-11-10T12:00:00Z'))],
                queue: queueEntry('FAILED', '2026-11-10T11:00:00Z'),
            },
            true,
            false,
        ],
        [
            'a queue attempt still testing after the pass',
            { commits: [commitWith(passed)], queue: queueEntry('TESTING', '2026-11-10T11:00:00Z') },
            true,
            false,
        ],
        [
            'a cancelled queue attempt after the pass',
            { commits: [commitWith(passed)], queue: queueEntry('CANCELLED', '2026-11-10T11:00:00Z') },
            true,
            false,
        ],
    ]
    for (const [label, { queue = null, ...shape }, passedExpected, rearmedExpected] of cases) {
        assert.deepEqual(
            fullRunState(pullRequest(shape), queue),
            { passed: passedExpected, rearmedByQueueKick: rearmedExpected },
            label
        )
    }
})
