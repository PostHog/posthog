import type {
    AIReportQueryDiagnosticApi,
    SubscriptionDeliveryApi,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'
import { SubscriptionDeliveryStatusEnumApi } from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { isPartialDelivery, stripDeliveryHistoryPointer } from './SubscriptionDeliveryHistory'

const diagnostic = (ok: boolean): AIReportQueryDiagnosticApi => ({
    description: 'q',
    hogql: 'SELECT 1',
    ok,
    error_type: ok ? null : 'ResolutionError',
})

describe('SubscriptionDeliveryHistory helpers', () => {
    describe('stripDeliveryHistoryPointer', () => {
        it.each([
            // The degraded notice loses only its "check the delivery history" pointer; the warning + body stay.
            [
                "> ⚠️ This report could not be generated — all 2 queries the assistant wrote failed to run. Check the subscription's delivery history in PostHog for the generated queries and errors.\n\n## Report\n\nbody",
                '> ⚠️ This report could not be generated — all 2 queries the assistant wrote failed to run.\n\n## Report\n\nbody',
            ],
            // A report without the pointer is returned unchanged (no over-stripping).
            ['## Weekly report\n\nAll good.', '## Weekly report\n\nAll good.'],
        ])('strips the in-app-redundant delivery-history pointer, leaving everything else', (input, expected) => {
            expect(stripDeliveryHistoryPointer(input)).toBe(expected)
        })
    })

    describe('isPartialDelivery', () => {
        it.each<[string, SubscriptionDeliveryApi['status'], AIReportQueryDiagnosticApi[] | null, boolean]>([
            // A completed delivery that couldn't run some queries is "partial", not a clean success.
            [
                'completed with a failed query',
                SubscriptionDeliveryStatusEnumApi.Completed,
                [diagnostic(true), diagnostic(false)],
                true,
            ],
            ['completed with all queries ok', SubscriptionDeliveryStatusEnumApi.Completed, [diagnostic(true)], false],
            // A fully-failed delivery is its own "Failed" state, never "partial".
            ['failed status', SubscriptionDeliveryStatusEnumApi.Failed, [diagnostic(false)], false],
            // Scrubbed/absent diagnostics (query-restricted caller, or a non-AI delivery) → not partial.
            ['completed with scrubbed diagnostics', SubscriptionDeliveryStatusEnumApi.Completed, null, false],
        ])('%s', (_name, status, diagnostics, expected) => {
            expect(isPartialDelivery({ status, ai_report_diagnostics: diagnostics })).toBe(expected)
        })
    })
})
