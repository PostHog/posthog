import { SignalReport } from 'products/signals/frontend/inbox/types'

import { reportWorkKind, todayNextStep } from './todayNextStep'
import { report } from './todayTestFixtures'

const RUN = { taskId: 't1', runId: 'r1' }

const CLAIMED_BY_TASK = report({
    assignee: {
        kind: 'task',
        task_id: 't1',
        claimed_at: '2026-08-11T09:00:00Z',
        user: null,
        agent: null,
        claim_id: 'c1',
    },
})

describe('todayNextStep', () => {
    test.each([
        [
            'an open pull request',
            report({
                pull_requests: [
                    { url: 'https://github.com/example/web/pull/1', state: 'draft', merged: false },
                ] as unknown as SignalReport['pull_requests'],
            }),
            null,
            {
                primary: { kind: 'review', url: 'https://github.com/example/web/pull/1', label: 'Review draft PR #1' },
                note: null,
            },
        ],
        [
            'a merged pull request',
            report({
                pull_requests: [
                    { url: 'https://github.com/example/web/pull/1', state: 'closed', merged: true },
                ] as unknown as SignalReport['pull_requests'],
            }),
            null,
            { primary: null, note: 'The fix is merged. Resolve the report once it is live.' },
        ],
        [
            'a task that claimed the report and has no run yet',
            CLAIMED_BY_TASK,
            null,
            { primary: { kind: 'start' }, note: 'A PostHog task picked this up on 11 Aug.' },
        ],
        [
            'a task that claimed the report and runs',
            CLAIMED_BY_TASK,
            RUN,
            {
                primary: { kind: 'open_task', label: 'Open the running task', taskId: 't1', runId: 'r1' },
                note: null,
            },
        ],
        [
            'a fix already in flight',
            report({ already_addressed: true }),
            null,
            { primary: null, note: 'A fix is already in flight. The full report links to it.' },
        ],
        ['an untouched report', report({}), null, { primary: { kind: 'start' }, note: null }],
    ])('names the next step for %s', (_, input, runningTask, expected) => {
        const { primary, note } = todayNextStep(input, {
            inFlightPullRequest: null,
            solutionNamesPullRequest: false,
            slotClaimed: false,
            runningTask,
        })
        expect({ primary, note }).toEqual(expected)
    })

    test.each([
        [
            'implement for a ready, actionable report',
            { actionability: 'immediately_actionable', status: 'ready' },
            'implement',
        ],
        [
            'investigate when it needs a person',
            { actionability: 'requires_human_input', status: 'pending_input' },
            'investigate',
        ],
    ])('chooses %s', (_, input, expected) => {
        expect(reportWorkKind(input as never)).toEqual(expected)
    })
})
