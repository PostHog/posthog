import { EnrichedTraceTreeNode } from './aiObservabilityTraceDataLogic'
import { computeBillingTotals } from './usePosthogAIBillingCalculations'

function makeNode(properties: Record<string, any>, children?: EnrichedTraceTreeNode[]): EnrichedTraceTreeNode {
    return {
        event: {
            id: `event-${Math.random()}`,
            event: '$ai_generation',
            properties,
            createdAt: '2026-01-01T00:00:00Z',
        },
        children,
        displayTotalCost: 0,
        displayLatency: 0,
        displayUsage: null,
    }
}

describe('computeBillingTotals', () => {
    it('applies markup per event, skipping pass-through products', () => {
        const tree = [
            makeNode({ $ai_billable: true, $ai_total_cost_usd: 10, ai_product: 'posthog_ai' }, [
                // Nested pass-through generation must still be summed, without markup
                makeNode({ $ai_billable: true, $ai_total_cost_usd: 5, ai_product: 'posthog_code' }),
            ]),
        ]

        expect(computeBillingTotals(tree)).toEqual({ totalCostUsd: 15, markupUsd: 2 })
    })

    it('excludes billable generations outside the billing whitelist', () => {
        // The usage reporter whitelists on ai_product — events with a missing or unknown
        // product never bill, even when tagged $ai_billable, so they must not display as billed.
        const tree = [
            makeNode({ $ai_billable: true, $ai_total_cost_usd: 10, ai_product: 'posthog_ai' }),
            makeNode({ $ai_billable: true, $ai_total_cost_usd: 5 }), // untagged
            makeNode({ $ai_billable: true, $ai_total_cost_usd: 5, ai_product: 'sherlockhog' }), // unbilled product
        ]

        expect(computeBillingTotals(tree)).toEqual({ totalCostUsd: 10, markupUsd: 2 })
    })

    it('ignores non-billable generations', () => {
        const tree = [makeNode({ $ai_billable: false, $ai_total_cost_usd: 10, ai_product: 'posthog_ai' })]

        expect(computeBillingTotals(tree)).toEqual({ totalCostUsd: 0, markupUsd: 0 })
    })
})
