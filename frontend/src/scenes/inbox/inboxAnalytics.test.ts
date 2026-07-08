import posthog from 'posthog-js'

import {
    captureInboxReportAction,
    captureInboxViewed,
    captureSignalSourceConnected,
    INBOX_EVENTS,
} from './inboxAnalytics'
import { SignalReport, SignalReportStatus } from './types'

jest.mock('posthog-js')

function lastCapture(event: string): Record<string, any> | undefined {
    const calls = (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)
    return calls.length > 0 ? calls[calls.length - 1][1] : undefined
}

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id: 'r1',
        title: 'Something broke',
        summary: null,
        status: SignalReportStatus.READY,
        total_weight: 1,
        signal_count: 1,
        relevant_user_count: null,
        created_at: '2026-06-20T00:00:00Z',
        updated_at: '2026-06-20T00:00:00Z',
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P1',
        actionability: 'immediately_actionable',
        ...overrides,
    }
}

describe('inboxAnalytics', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
    })

    it('stamps every event with the cloud client discriminator', () => {
        captureInboxViewed({
            tab: 'reports',
            reports: [],
            totalCount: 0,
            hasActiveFilters: false,
            sourceProductFilter: [],
            priorityFilter: [],
            scope: 'for-you',
        })
        expect(lastCapture(INBOX_EVENTS.VIEWED)?.inbox_client).toBe('cloud')
    })

    it('breaks the visible reports down by priority and actionability', () => {
        captureInboxViewed({
            tab: 'reports',
            reports: [
                makeReport({ id: 'a', priority: 'P0', actionability: 'immediately_actionable' }),
                makeReport({ id: 'b', priority: 'P1', actionability: 'requires_human_input' }),
                makeReport({ id: 'c', priority: null, actionability: null }),
            ],
            totalCount: 3,
            hasActiveFilters: true,
            sourceProductFilter: ['error_tracking'],
            priorityFilter: ['P0'],
            scope: 'entire-project',
        })
        const props = lastCapture(INBOX_EVENTS.VIEWED)
        expect(props).toMatchObject({
            report_count: 3,
            total_count: 3,
            is_empty: false,
            has_active_filters: true,
            source_product_filter: ['error_tracking'],
            priority_p0_count: 1,
            priority_p1_count: 1,
            priority_unknown_count: 1,
            actionability_immediately_actionable_count: 1,
            actionability_requires_human_input_count: 1,
            actionability_unknown_count: 1,
        })
    })

    it('emits a single-report action with the report context', () => {
        captureInboxReportAction({
            report: makeReport(),
            actionType: 'create_pr',
            surface: 'detail_pane',
        })
        expect(lastCapture(INBOX_EVENTS.REPORT_ACTION)).toMatchObject({
            report_id: 'r1',
            action_type: 'create_pr',
            surface: 'detail_pane',
            is_bulk: false,
            bulk_size: 1,
        })
    })

    it('emits a bulk action with a null report and the selection size', () => {
        captureInboxReportAction({
            actionType: 'dismiss',
            surface: 'bulk_bar',
            isBulk: true,
            bulkSize: 4,
            extra: { dismissal_reason: 'wontfix_irrelevant' },
        })
        expect(lastCapture(INBOX_EVENTS.REPORT_ACTION)).toMatchObject({
            report_id: null,
            action_type: 'dismiss',
            surface: 'bulk_bar',
            is_bulk: true,
            bulk_size: 4,
            dismissal_reason: 'wontfix_irrelevant',
        })
    })

    it('records a connected source with first-connection and wizard flags', () => {
        captureSignalSourceConnected({
            sourceProduct: 'github',
            sourceType: 'issue',
            isFirstConnection: true,
            viaSetupWizard: true,
        })
        expect(lastCapture(INBOX_EVENTS.SOURCE_CONNECTED)).toMatchObject({
            source_product: 'github',
            source_type: 'issue',
            is_first_connection: true,
            via_setup_wizard: true,
        })
    })
})
