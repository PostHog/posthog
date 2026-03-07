import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'

import type { BillingProductV2Type } from '~/types'

import type { productExplorerLogicType } from './productExplorerLogicType'
import {
    type ProductExplorerNodeData,
} from './ProductExplorerNode'
import { type ProductNodeStatus, type ProductTreeNode, PRODUCT_NODES } from './productTreeData'

export const productExplorerLogic = kea<productExplorerLogicType>([
    path(['products', 'analytics_platform', 'frontend', 'ProductExplorer', 'productExplorerLogic']),

    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            billingLogic,
            ['billing'],
        ],
        actions: [billingLogic, ['loadBilling']],
    })),

    actions({
        setSelectedNode: (node: ProductExplorerNodeData | null) => ({ node }),
        closePanel: true,
    }),

    reducers({
        selectedNode: [
            null as ProductExplorerNodeData | null,
            {
                setSelectedNode: (_, { node }) => node,
                closePanel: () => null,
            },
        ],
    }),

    selectors({
        billingProducts: [
            (s) => [s.billing],
            (billing): Record<string, BillingProductV2Type> => {
                const map: Record<string, BillingProductV2Type> = {}
                if (billing?.products) {
                    for (const product of billing.products) {
                        map[product.type] = product
                    }
                }
                return map
            },
        ],

        completedOnboarding: [
            (s) => [s.currentTeam],
            (team): Record<string, boolean> => {
                return (team?.has_completed_onboarding_for as Record<string, boolean>) || {}
            },
        ],

        activatedProducts: [
            (s) => [s.currentTeam],
            (team): Set<string> => {
                const activated = new Set<string>()
                if (team?.product_intents) {
                    for (const intent of team.product_intents) {
                        activated.add(intent.product_type)
                    }
                }
                return activated
            },
        ],

        nodeStatusMap: [
            (s) => [s.billingProducts, s.completedOnboarding, s.activatedProducts],
            (billingProducts, completedOnboarding, activatedProducts): Record<string, ProductNodeStatus> => {
                const statusMap: Record<string, ProductNodeStatus> = {}

                for (const node of PRODUCT_NODES) {
                    if (node.id === 'events_core') {
                        statusMap[node.id] = 'unlocked'
                        continue
                    }

                    if (node.comingSoon || node.featureFlag) {
                        statusMap[node.id] = 'coming_soon'
                        continue
                    }

                    if (node.productKey) {
                        const billingProduct = billingProducts[node.productKey]
                        const hasCompleted = completedOnboarding[node.productKey]
                        const isSubscribed = billingProduct?.subscribed
                        const hasUsage = (billingProduct?.current_usage ?? 0) > 0
                        const hasIntent = activatedProducts.has(node.productKey)

                        if (hasCompleted || isSubscribed || hasUsage || hasIntent) {
                            statusMap[node.id] = 'unlocked'
                        } else {
                            statusMap[node.id] = 'available'
                        }
                    } else {
                        statusMap[node.id] = 'available'
                    }
                }

                return statusMap
            },
        ],

        enrichedNodes: [
            (s) => [s.nodeStatusMap, s.billingProducts],
            (nodeStatusMap, billingProducts): ProductExplorerNodeData[] => {
                return PRODUCT_NODES.map((node) => {
                    const status = nodeStatusMap[node.id] || 'available'
                    const billingProduct = node.productKey ? billingProducts[node.productKey] : undefined

                    const enriched: ProductExplorerNodeData = {
                        ...node,
                        status,
                    }

                    if (status === 'unlocked' && billingProduct) {
                        enriched.usagePercent = billingProduct.percentage_usage ?? 0
                        const usage = billingProduct.current_usage ?? 0
                        const limit = billingProduct.free_allocation ?? billingProduct.usage_limit
                        if (limit) {
                            enriched.usageLabel = `${formatUsage(usage)} / ${formatUsage(limit)}`
                        } else {
                            enriched.usageLabel = formatUsage(usage)
                        }
                        enriched.freeAllocation = billingProduct.free_allocation
                            ? formatUsage(billingProduct.free_allocation)
                            : undefined
                    }

                    return enriched
                })
            },
        ],

        unlockedCount: [
            (s) => [s.nodeStatusMap],
            (nodeStatusMap): number => {
                return Object.values(nodeStatusMap).filter((s) => s === 'unlocked').length - 1 // exclude core
            },
        ],

        totalProducts: [
            () => [],
            (): number => {
                return PRODUCT_NODES.filter((n) => n.id !== 'events_core').length
            },
        ],

        availableProducts: [
            (s) => [s.nodeStatusMap],
            (nodeStatusMap): ProductTreeNode[] => {
                return PRODUCT_NODES.filter((n) => nodeStatusMap[n.id] === 'available')
            },
        ],

        nextRecommendation: [
            (s) => [s.availableProducts],
            (availableProducts): ProductTreeNode | null => {
                // Recommend the first available product that isn't coming soon
                return availableProducts.find((p) => !p.comingSoon) || null
            },
        ],

    }),

    afterMount(({ actions }) => {
        actions.loadBilling()
    }),
])

function formatUsage(value: number): string {
    if (value >= 1_000_000_000) {
        return `${(value / 1_000_000_000).toFixed(1)}B`
    }
    if (value >= 1_000_000) {
        return `${(value / 1_000_000).toFixed(1)}M`
    }
    if (value >= 1_000) {
        return `${(value / 1_000).toFixed(1)}K`
    }
    return value.toString()
}
