import { EnrichedTraceTreeNode } from './aiObservabilityTraceDataLogic'
import { computeBillingTotals, getMarkupPercentForProduct } from './usePosthogAIBillingCalculations'

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

describe('getMarkupPercentForProduct', () => {
    it.each([
        ['posthog_code', 0],
        ['posthog_ai', 0.2],
        ['slack_app', 0.2],
        [undefined, 0.2],
    ])('returns the right markup for %s', (aiProduct, expected) => {
        expect(getMarkupPercentForProduct(aiProduct)).toBe(expected)
    })
})

describe('computeBillingTotals', () => {
    it('applies markup per event, skipping pass-through products', () => {
        const tree = [
            makeNode(
                { $ai_billable: true, $ai_total_cost_usd: 10, ai_product: 'posthog_ai' },
                // Nested pass-through generation must still be summed, without markup
                [makeNode({ $ai_billable: true, $ai_total_cost_usd: 5, ai_product: 'posthog_code' })]
            ),
        ]

        expect(computeBillingTotals(tree)).toEqual({ totalCostUsd: 15, markupUsd: 2 })
    })

    it('ignores non-billable generations', () => {
        const tree = [makeNode({ $ai_billable: false, $ai_total_cost_usd: 10, ai_product: 'posthog_ai' })]

        expect(computeBillingTotals(tree)).toEqual({ totalCostUsd: 0, markupUsd: 0 })
    })
})
