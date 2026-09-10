import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
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
    rows_read: 8_400_000_000,
    duration_ms: 19_000,
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
        uiCustomizationLogic().mount()
    })

    afterEach(() => cleanup())

    it.each([
        { label: 'nothing to advise', findings: [], adviceHidden: false, advice: null, fixer: false },
        {
            label: 'a finding the assistant can fix',
            findings: [FINDING],
            adviceHidden: false,
            advice: FINDING.message,
            fixer: true,
        },
        {
            label: 'a finding fixed on the insight',
            findings: [INSIGHT_SIDE_FINDING],
            adviceHidden: false,
            advice: INSIGHT_SIDE_FINDING.message,
            fixer: false,
        },
        { label: 'advice turned off', findings: [FINDING], adviceHidden: true, advice: null, fixer: false },
    ])('keeps the stat line and shows $label', ({ findings, adviceHidden, advice, fixer }) => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            ui_configuration: { version: 1, hide_query_scan_advice: adviceHidden },
        })

        render(
            <Provider>
                <QueryScanBanner
                    queryScan={{ summary: SUMMARY, findings, cacheKey: 'cache-key' }}
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
