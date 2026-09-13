import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { QueryScanBanner } from './QueryScanBanner'

const SUMMARY: QueryScanSummary = {
    mode: 'show',
    rows_read: 8_400_000_000,
    duration_ms: 19_000,
    status: 'done',
}

const FINDING: QueryScanWarning = {
    type: 'query_scan',
    kind: 'no_event_filter',
    message: 'This query read every event in its date range.',
    fix: 'Add an event filter naming the events this question is about.',
}

const INSIGHT_SIDE_FINDING: QueryScanWarning = {
    ...FINDING,
    kind: 'no_start_date',
    reason: 'filters',
    message: 'No date range is set for this insight or dashboard.',
    fix: 'Set a date range on the insight or the dashboard.',
}

describe('QueryScanBanner', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => cleanup())

    it.each([
        { label: 'nothing to advise', findings: [], assistantPrompt: null, advice: null, fixer: false },
        {
            label: 'a finding the assistant can fix',
            findings: [FINDING],
            assistantPrompt: 'Help me get what this query is trying to find, as fast as possible.',
            advice: FINDING.message,
            fixer: true,
        },
        // The backend sends no prompt for a finding fixed on the insight, so there is nothing to hand the assistant.
        {
            label: 'a finding fixed on the insight',
            findings: [INSIGHT_SIDE_FINDING],
            assistantPrompt: null,
            advice: INSIGHT_SIDE_FINDING.message,
            fixer: false,
        },
    ])('keeps the stat line and shows $label', ({ findings, assistantPrompt, advice, fixer }) => {
        render(
            <Provider>
                <QueryScanBanner
                    queryScan={{ summary: SUMMARY, findings, cacheKey: 'cache-key', assistantPrompt }}
                    onFixWithAI={jest.fn()}
                />
            </Provider>
        )

        expect(screen.getByText(/Read 8,400,000,000 rows in 19.0 s/)).toBeVisible()
        const shown = findings.map((finding) => finding.message).filter((message) => screen.queryByText(message))
        expect(shown).toEqual(advice ? [advice] : [])
        expect(!!screen.queryByText('Fix with AI')).toBe(fixer)
    })
})
