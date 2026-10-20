// Run with: node --test .github/scripts/image-build-cancellations.test.js

const { describe, it } = require('node:test')
const assert = require('node:assert/strict')

const imageBuildCancellations = require('./image-build-cancellations')

const context = { repo: { owner: 'PostHog', repo: 'posthog' } }

function cancelledRuns(name, count) {
    return Array.from({ length: count }, (_, i) => ({ name, html_url: `https://github.com/runs/${name}/${i}` }))
}

// Returns the runs only for a query scoped to cancelled master push runs in a time window, so a
// script that drops a filter and would count every run sees none here.
function fakeGithub(runsByWorkflow) {
    return {
        rest: {
            actions: {
                listWorkflowRuns: async ({ workflow_id, branch, event, status, created }) => {
                    const scoped =
                        branch === 'master' && event === 'push' && status === 'cancelled' && created?.startsWith('>=')
                    return { data: { workflow_runs: scoped ? runsByWorkflow[workflow_id] || [] : [] } }
                },
            },
        },
    }
}

function fakeSlack(messages) {
    const calls = { postMessage: [], update: [] }
    return {
        calls,
        history: async () => ({ messages }),
        postMessage: async (args) => calls.postMessage.push(args),
        update: async (args) => calls.update.push(args),
    }
}

const activeAnchor = {
    ts: '1.0',
    metadata: { event_type: 'image_build_cancellations', event_payload: { status: 'active' } },
}
const resolvedAnchor = {
    ts: '0.5',
    metadata: { event_type: 'image_build_cancellations', event_payload: { status: 'resolved' } },
}

describe('image build cancellations', () => {
    const cases = [
        { title: 'opens an alert at the threshold', cancelled: 3, history: [resolvedAnchor], posts: 1, updates: [] },
        {
            title: 'updates an open alert instead of posting again',
            cancelled: 5,
            history: [activeAnchor],
            posts: 0,
            updates: ['active'],
        },
        {
            title: 'resolves an open alert once runs stop being cancelled',
            cancelled: 2,
            history: [activeAnchor],
            posts: 0,
            updates: ['resolved'],
        },
        {
            title: 'stays quiet below the threshold with no open alert',
            cancelled: 2,
            history: [],
            posts: 0,
            updates: [],
        },
    ]
    for (const { title, cancelled, history, posts, updates } of cases) {
        it(title, async () => {
            process.env.IMAGE_BUILD_WORKFLOWS = 'ci-nodejs-container.yml,rust-docker-build.yml'
            process.env.CANCELLED_BUILD_THRESHOLD = '3'
            process.env.CANCELLED_BUILD_LOOKBACK_MINUTES = '120'
            const github = fakeGithub({ 'ci-nodejs-container.yml': cancelledRuns('Node image', cancelled) })
            const slack = fakeSlack(history)

            await imageBuildCancellations({ context, github }, { slack })

            assert.equal(slack.calls.postMessage.length, posts)
            assert.deepEqual(
                slack.calls.update.map((args) => args.metadata.event_payload.status),
                updates
            )
            for (const args of slack.calls.update) {
                assert.equal(args.ts, activeAnchor.ts)
            }
        })
    }
})
