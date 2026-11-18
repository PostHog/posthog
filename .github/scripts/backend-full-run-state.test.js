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
const trunkComment = (body, updatedAt, login = 'trunk-io') => ({ author: { login }, body, updatedAt })
const KICKED = 'This PR has been removed from the merge queue because it failed tests.'

const pullRequest = ({ commits = [], replacedHeads = [], comments = [], olderComments = false }) => ({
    commits: { nodes: commits.map((commit) => ({ commit })) },
    timelineItems: { nodes: replacedHeads.map((beforeCommit) => ({ beforeCommit })) },
    comments: { pageInfo: { hasPreviousPage: olderComments }, nodes: comments },
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
            'a queue kick after the pass',
            { commits: [commitWith(passed)], comments: [trunkComment(KICKED, '2026-11-10T11:00:00Z')] },
            false,
            true,
        ],
        [
            'a queue kick before a later pass',
            {
                commits: [commitWith(passed), commitWith(gateCheck('SUCCESS', '2026-11-10T12:00:00Z'))],
                comments: [trunkComment(KICKED, '2026-11-10T11:00:00Z', 'trunk-io[bot]')],
            },
            true,
            false,
        ],
        [
            'kick wording from someone other than Trunk',
            { commits: [commitWith(passed)], comments: [trunkComment(KICKED, '2026-11-10T11:00:00Z', 'someone')] },
            true,
            false,
        ],
        [
            'older comments unread and no Trunk comment among the newer ones',
            {
                commits: [commitWith(passed)],
                comments: [trunkComment('LGTM', '2026-11-10T11:00:00Z', 'someone')],
                olderComments: true,
            },
            false,
            false,
        ],
        [
            'older comments unread but Trunk comment read without a failure',
            {
                commits: [commitWith(passed)],
                comments: [trunkComment('This PR is in the merge queue.', '2026-11-10T11:00:00Z')],
                olderComments: true,
            },
            true,
            false,
        ],
        [
            'a queue removal because the branch was pushed to',
            {
                commits: [commitWith(passed)],
                comments: [
                    trunkComment('removed from the merge queue because it was pushed to', '2026-11-10T11:00:00Z'),
                ],
            },
            true,
            false,
        ],
    ]
    for (const [label, shape, passedExpected, rearmedExpected] of cases) {
        assert.deepEqual(
            fullRunState(pullRequest(shape)),
            { passed: passedExpected, rearmedByQueueKick: rearmedExpected },
            label
        )
    }
})
