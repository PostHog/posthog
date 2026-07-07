import { useValues } from 'kea'
import { useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EnrichedTraceTreeNode } from './aiObservabilityTraceDataLogic'
import { isLLMEvent } from './utils'

// AI billing markup: 20% markup on top of cost. Some products bill model costs as
// pure pass-through (no markup) — keep in sync with posthog/tasks/usage_report.py.
const AI_COST_MARKUP_PERCENT = 0.2
const PASS_THROUGH_AI_PRODUCTS = new Set(['posthog_code'])

export function getMarkupPercentForProduct(aiProduct: unknown): number {
    return typeof aiProduct === 'string' && PASS_THROUGH_AI_PRODUCTS.has(aiProduct) ? 0 : AI_COST_MARKUP_PERCENT
}

export function computeBillingTotals(enrichedTree: EnrichedTraceTreeNode[]): {
    totalCostUsd: number
    markupUsd: number
} {
    let totalCostUsd = 0
    let markupUsd = 0
    const sumBilled = (node: EnrichedTraceTreeNode): void => {
        const ev = node.event
        if (isLLMEvent(ev) && ev.event === '$ai_generation' && !!ev.properties?.$ai_billable) {
            const cost = Number(ev.properties.$ai_total_cost_usd ?? 0)
            if (!isNaN(cost)) {
                totalCostUsd += cost
                markupUsd += cost * getMarkupPercentForProduct(ev.properties.ai_product)
            }
        }
        if (node.children) {
            for (const child of node.children) {
                sumBilled(child)
            }
        }
    }

    for (const node of enrichedTree) {
        sumBilled(node)
    }
    return { totalCostUsd, markupUsd }
}

// Banker's rounding
function roundBankers(value: number): number {
    const rounded = Math.round(value)
    const diff = Math.abs(value - rounded + 0.5)

    // If not exactly X.5 (accounting for floating-point precision), use standard rounding
    if (diff > Number.EPSILON) {
        return Math.round(value)
    }

    // For X.5, round to nearest even
    const lower = Math.floor(value)
    return lower % 2 === 0 ? lower : lower + 1
}

interface BillingCalculations {
    showBillingInfo: boolean
    totalCostUsd: number
    markupUsd: number
    billedTotalUsd: number
    billedCredits: number
}

export function usePosthogAIBillingCalculations(enrichedTree: EnrichedTraceTreeNode[] | null): BillingCalculations {
    const { featureFlags } = useValues(featureFlagLogic)

    const showBillingInfo = !!featureFlags[FEATURE_FLAGS.POSTHOG_AI_BILLING_DISPLAY]

    // Compute total billed USD and per-product markup across billed generations in the tree
    const { totalCostUsd, markupUsd } = useMemo(() => {
        if (!showBillingInfo || !enrichedTree) {
            return { totalCostUsd: 0, markupUsd: 0 }
        }
        return computeBillingTotals(enrichedTree)
    }, [enrichedTree, showBillingInfo])

    const billedTotalUsd = totalCostUsd + markupUsd // Total cost + markup
    const billedCredits = roundBankers(billedTotalUsd * 100)

    return {
        showBillingInfo,
        totalCostUsd,
        markupUsd,
        billedTotalUsd,
        billedCredits,
    }
}
