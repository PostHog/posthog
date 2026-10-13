import { IconGraph, IconLineGraph, IconFolderOpen, IconDocument } from '@posthog/icons'

import { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { urls } from 'scenes/urls'

import { ProjectTreeRef } from '~/types'

import { ProductIconWrapper } from './defaultTree'
import { isProjectTreeItemActive } from './utils'

const ANALYTICS_PRODUCTS = ['Product analytics', 'Web analytics', 'Marketing analytics']

/** Keeps saved product identities intact while grouping the original sidebar's rows. */
export function groupLegacyAnalyticsNavigation(
    items: TreeDataItem[],
    availableProducts: TreeDataItem[]
): TreeDataItem[] {
    const selectedAnalytics = new Map(
        items.filter((item) => ANALYTICS_PRODUCTS.includes(item.record?.path)).map((item) => [item.record?.path, item])
    )
    const analytics =
        selectedAnalytics.size > 0
            ? availableProducts
                  .filter((item) => ANALYTICS_PRODUCTS.includes(item.record?.path))
                  .map(
                      (item) =>
                          selectedAnalytics.get(item.record?.path) ?? {
                              ...item,
                              id: `custom-products/${item.record?.path}`,
                              record: { ...item.record, protocol: 'custom-products://' },
                          }
                  )
            : []
    const dashboard = items.find((item) => item.record?.path === 'Dashboards')
    const result: TreeDataItem[] = []
    let analyticsAdded = false
    const analyticsGroup: TreeDataItem = {
        id: 'legacy-navigation/analytics',
        name: 'Analytics',
        displayName: 'Analytics',
        icon: (
            <ProductIconWrapper
                type="product_analytics"
                colorOverride={[
                    'var(--color-product-product-analytics-light)',
                    'var(--color-product-product-analytics-dark)',
                ]}
            >
                <IconLineGraph />
            </ProductIconWrapper>
        ),
        children: analytics.sort(
            (a, b) => ANALYTICS_PRODUCTS.indexOf(a.record?.path) - ANALYTICS_PRODUCTS.indexOf(b.record?.path)
        ),
    }

    for (const item of items) {
        if (item.type === 'category' && item.name === 'Analytics') {
            continue
        }
        if (ANALYTICS_PRODUCTS.includes(item.record?.path)) {
            if (!analyticsAdded) {
                result.push(analyticsGroup)
                analyticsAdded = true
            }
            continue
        }
        if (item === dashboard) {
            if (analytics.length > 0 && !analyticsAdded) {
                result.push(analyticsGroup)
                analyticsAdded = true
            }
            result.push({
                id: 'legacy-navigation/reports',
                name: 'Custom dashboards',
                displayName: 'Custom dashboards',
                icon: (
                    <ProductIconWrapper
                        type="dashboard"
                        colorOverride={[
                            'var(--color-product-dashboards-light)',
                            'var(--color-product-dashboards-dark)',
                        ]}
                    >
                        <IconDocument />
                    </ProductIconWrapper>
                ),
                record: { path: 'Custom dashboards', type: 'folder', href: urls.reports(), sceneKey: 'Reports' },
                children: [
                    {
                        id: 'legacy-navigation/folders',
                        name: 'Folders',
                        displayName: 'Folders',
                        icon: <IconFolderOpen />,
                        record: { path: 'Folders', href: urls.reports() },
                    },
                    dashboard,
                    {
                        id: 'legacy-navigation/insights',
                        name: 'Insights',
                        displayName: 'Insights',
                        icon: <IconGraph />,
                        record: { path: 'Insights', href: urls.reportsInsights(), type: 'insight' },
                    },
                ],
            })
            continue
        }
        result.push(item)
    }
    return result
}

export function isLegacyAnalyticsNavigationItemActive(
    item: TreeDataItem,
    currentPath: string,
    ref: ProjectTreeRef | null
): boolean {
    if (currentPath.startsWith('/insights/')) {
        if (item.id === 'legacy-navigation/reports' || item.id === 'legacy-navigation/insights') {
            return true
        }
        if (item.record?.path === 'Product analytics') {
            return false
        }
    }
    return isProjectTreeItemActive(item, currentPath, ref)
}
