import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'

import { type TodayReportState } from './todayReportState'
import { reportRowFacts } from './todayRowFacts'

describe('reportRowFacts', () => {
    it.each([
        {
            name: 'a report without a reason keeps the update time',
            personalReason: null,
            facts: ['Fix ready for review', 'Updated'],
            reason: null,
        },
        {
            name: 'a reason takes the place of the update time, without its full stop',
            personalReason: 'You reviewed the last two fixes in this area.',
            facts: ['Fix ready for review'],
            reason: 'You reviewed the last two fixes in this area',
        },
        {
            name: 'a verdict hides the reason',
            personalReason: 'You reviewed the last two fixes in this area.',
            state: 'dismissed' as TodayReportState,
            facts: ['Dismissed'],
            reason: null,
        },
    ])('$name', ({ personalReason, state, facts, reason }) => {
        const report = makeReport({
            implementation_pr_url: 'https://github.com/example/repo/pull/1',
            implementation_pr_state: 'open',
            personal_reason: personalReason,
        })
        const result = reportRowFacts(report, state)
        // The update time is relative to now, so only its prefix is stable.
        expect(result.facts.map((fact) => fact.replace(/^Updated .+$/, 'Updated'))).toEqual(facts)
        expect(result.reason).toEqual(reason)
    })
})
