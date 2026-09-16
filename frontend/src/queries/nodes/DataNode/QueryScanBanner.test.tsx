import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { QueryScanSummary, QueryScanWarning } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { QueryScanBanner } from './QueryScanBanner'

const SUMMARY: QueryScanSummary = {
    rows_read: 8_400_000_000,
    duration_ms: 19_000,
    analysis_requested: true,
}

const FINDING: QueryScanWarning = {
    kind: 'no_event_filter',
    message: 'This query read every event in its date range.',
    fix: 'Add an event filter naming the events this question is about.',
    actionable: true,
}

const INSIGHT_SIDE_FINDING: QueryScanWarning = {
    ...FINDING,
    kind: 'no_start_date',
    reason: 'filters',
    message: 'No date range is set for this insight or dashboard.',
    fix: 'Set a date range on the insight or the dashboard.',
}

const BY_DESIGN_FINDING: QueryScanWarning = {
    ...FINDING,
    kind: 'no_start_date',
    reason: 'all_history',
    message: 'This query finds a first event ever, so it reads all your data by design.',
    fix: 'Do not propose a time bound for that read.',
    actionable: false,
}

describe('QueryScanBanner', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => cleanup())

    it.each([
        {
            label: 'nothing to advise',
            findings: [],
            assistantPrompt: null,
            advice: [],
            banner: false,
            fixer: false,
        },
        {
            label: 'a finding the assistant can fix',
            findings: [FINDING],
            assistantPrompt: 'Help me get what this query is trying to find, as fast as possible.',
            advice: [FINDING.message],
            banner: true,
            fixer: true,
        },
        // The backend sends no prompt for a finding fixed on the insight, so there is nothing to hand the assistant.
        {
            label: 'a finding fixed on the insight',
            findings: [INSIGHT_SIDE_FINDING],
            assistantPrompt: null,
            advice: [INSIGHT_SIDE_FINDING.message],
            banner: true,
            fixer: false,
        },
        // A by-design finding explains the read; shown as a note, it must not read as something to fix.
        {
            label: 'a finding the person cannot act on',
            findings: [BY_DESIGN_FINDING],
            assistantPrompt: null,
            advice: [BY_DESIGN_FINDING.message],
            banner: false,
            fixer: false,
        },
        {
            label: 'a by-design finding beside one to act on',
            findings: [BY_DESIGN_FINDING, FINDING],
            assistantPrompt: 'Help me get what this query is trying to find, as fast as possible.',
            advice: [BY_DESIGN_FINDING.message, FINDING.message],
            banner: true,
            fixer: true,
        },
    ])('keeps the stat line and shows $label', ({ findings, assistantPrompt, advice, banner, fixer }) => {
        const { container } = render(
            <Provider>
                <QueryScanBanner
                    queryScan={{
                        summary: SUMMARY,
                        findings,
                        actionable: findings.some((finding) => finding.actionable),
                        cacheKey: 'cache-key',
                        assistantPrompt,
                    }}
                    onFixWithAI={jest.fn()}
                />
            </Provider>
        )

        expect(screen.getByText(/Read 8,400,000,000 rows in 19.0 s/)).toBeVisible()
        const shown = findings.map((finding) => finding.message).filter((message) => screen.queryByText(message))
        expect(shown).toEqual(advice)
        expect(!!container.querySelector('.LemonBanner')).toBe(banner)
        expect(!!container.querySelector('[data-attr="query-scan-note"]')).toBe(advice.length > 0 && !banner)
        expect(!!screen.queryByText('Fix with AI')).toBe(fixer)
    })
})
