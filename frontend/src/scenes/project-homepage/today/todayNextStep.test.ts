import { SignalReport } from 'products/signals/frontend/inbox/types'

import { inFlightPullRequest, reportWorkKind, todayNextStep } from './todayNextStep'
import { todayReportSections } from './todayReportSections'
import { report } from './todayTestFixtures'

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
            false,
            {
                primary: { kind: 'review', url: 'https://github.com/example/web/pull/1', label: 'Review draft PR #1' },
                note: null,
            },
        ],
        [
            'a task that claimed the report and has no run yet',
            CLAIMED_BY_TASK,
            false,
            { primary: { kind: 'start' }, note: 'A PostHog task picked this up on 11 Aug.' },
        ],
        [
            'a task that claimed the report and runs',
            CLAIMED_BY_TASK,
            true,
            { primary: { kind: 'open_task', label: 'Open the running task' }, note: null },
        ],
        [
            'a fix already in flight',
            report({ already_addressed: true }),
            false,
            { primary: null, note: 'A fix is already in flight. The full report links to it.' },
        ],
        ['an untouched report', report({}), false, { primary: { kind: 'start' }, note: null }],
    ])('names the next step for %s', (_, input, hasRun, expected) => {
        const { primary, note } = todayNextStep(input, {
            proposal: todayReportSections(input.summary).proposal,
            slotClaimed: false,
            hasRun,
        })
        expect({ primary, note }).toEqual(expected)
    })

    test.each([
        ['one pull request', 'Open PR https://github.com/example/web/pull/7 covers it.', '7'],
        [
            'several pull requests',
            'Merged in https://github.com/example/web/pull/7, review https://github.com/example/web/pull/8.',
            null,
        ],
        [
            'several pull requests, one named by the proposal',
            'Lead.\n\n## Problem\n\nMerged in https://github.com/example/web/pull/7.\n\n## Solution\n\nReuse draft https://github.com/example/web/pull/9.',
            '9',
        ],
    ])('names the in-flight pull request for %s', (_, summary, expected) => {
        expect(inFlightPullRequest(report({ summary }), todayReportSections(summary).proposal)?.number ?? null).toEqual(
            expected
        )
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
