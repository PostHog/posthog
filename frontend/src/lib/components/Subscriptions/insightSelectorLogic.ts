import { actions, connect, kea, path, props, reducers, selectors } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, DashboardTile, InsightModel } from '~/types'

import type { insightSelectorLogicType } from './insightSelectorLogicType'

// Per-subscription insight caps. The live cap comes from the `subscription_insights` billing
// entitlement; these are the fallbacks used until billing emits it. Keep in sync with
// FREE_TIER_MAX_ASSET_COUNT and DEFAULT_MAX_ASSET_COUNT in
// ee/tasks/subscriptions/subscription_utils.py — the backend enforces, this is the matching UX cap.
export const FREE_TIER_MAX_INSIGHTS = 6
export const PAID_TIER_MAX_INSIGHTS = 25

export interface InsightSelectorLogicProps {
    tiles: DashboardTile[]
}

export const insightSelectorLogic = kea<insightSelectorLogicType>([
    props({} as InsightSelectorLogicProps),
    path(['lib', 'components', 'Subscriptions', 'insightSelectorLogic']),

    connect(() => ({
        values: [userLogic, ['user', 'availableFeature']],
    })),

    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setUserHasInteracted: true,
    }),

    reducers({
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        userHasInteracted: [false, { setUserHasInteracted: () => true }],
    }),

    selectors({
        // Driven by the `subscription_insights` billing entitlement (mirrors the backend
        // get_max_asset_count_for_organization). Until billing emits it, fall back to the plan
        // tier — paid orgs (any product feature present) get the higher cap, free orgs the lower.
        maxInsights: [
            (s) => [s.availableFeature, s.user],
            (availableFeature, user): number => {
                const feature = availableFeature(AvailableFeature.SUBSCRIPTION_INSIGHTS)
                if (feature) {
                    return feature.limit ?? PAID_TIER_MAX_INSIGHTS
                }
                return user?.organization?.available_product_features?.length
                    ? PAID_TIER_MAX_INSIGHTS
                    : FREE_TIER_MAX_INSIGHTS
            },
        ],
        insightTiles: [
            (_, p) => [p.tiles],
            (tiles): DashboardTile<InsightModel>[] =>
                ((tiles || []) as DashboardTile<InsightModel>[])
                    .filter(
                        (tile): tile is DashboardTile<InsightModel> =>
                            !!tile.insight && !tile.deleted && !tile.insight.deleted
                    )
                    .sort(
                        (a, b) =>
                            (a.layouts?.sm?.y ?? 100) - (b.layouts?.sm?.y ?? 100) ||
                            (a.layouts?.sm?.x ?? 100) - (b.layouts?.sm?.x ?? 100)
                    ),
        ],
        filteredTiles: [
            (s) => [s.insightTiles, s.searchTerm],
            (insightTiles, searchTerm): DashboardTile<InsightModel>[] => {
                if (!searchTerm.trim()) {
                    return insightTiles
                }
                const lowerSearch = searchTerm.toLowerCase()
                return insightTiles.filter((tile) => {
                    const name = tile.insight?.name || tile.insight?.derived_name || ''
                    return name.toLowerCase().includes(lowerSearch)
                })
            },
        ],
        showSearch: [(s) => [s.insightTiles], (insightTiles) => insightTiles.length > 10],
    }),
])
