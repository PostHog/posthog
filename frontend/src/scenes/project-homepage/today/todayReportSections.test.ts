import { todayReportSections } from './todayReportSections'

describe('todayReportSections', () => {
    test.each([
        [
            'markdown headings',
            'Lead sentence.\n\n## Problem\n\nBroken.\n\n## Impact\n\n**12 people** hit it. [Failures](chart:failures)\n\n## Solution\n\nFix the key.\n\n## Expected impact\n\nZero errors.',
            {
                lead: 'Lead sentence.',
                impact: '**12 people** hit it.',
                proposal: 'Fix the key.',
            },
        ],
        [
            'bold paragraph headings',
            'Lead sentence.\n\n**Evidence**\n\n- A finding.\n\n**Recommended next step**\n\n- Inspect the [rate](chart:rate) path.',
            {
                lead: 'Lead sentence.',
                impact: null,
                proposal: '- Inspect the rate path.',
            },
        ],
        [
            'a bold lead sentence',
            '**One-page checkout won. It is safe to ship.**\n\nThe shorter checkout completed more often.',
            {
                lead: '**One-page checkout won. It is safe to ship.**',
                impact: null,
                proposal: null,
            },
        ],
        ['no headings', 'Only a lead.\n\nA second paragraph.', { lead: 'Only a lead.', impact: null, proposal: null }],
    ])('splits a summary with %s', (_, summary, expected) => {
        expect(todayReportSections(summary)).toEqual(expected)
    })
})
