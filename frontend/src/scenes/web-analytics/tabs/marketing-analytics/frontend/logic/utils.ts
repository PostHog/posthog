import { DataWarehouseNode } from '~/queries/schema/schema-general'
import { ExternalDataSourceType, ManualLinkSourceType } from '~/types'

import { NativeSource } from './marketingAnalyticsLogic'
import { googleAdsCostTile } from './marketingCostTile'

export type NativeMarketingSource = Extract<ExternalDataSourceType, 'GoogleAds' | 'MetaAds'>
export type NonNativeMarketingSource = Extract<ExternalDataSourceType, 'BigQuery'>

export const VALID_NATIVE_MARKETING_SOURCES: NativeMarketingSource[] = ['GoogleAds', 'MetaAds']
export const VALID_NON_NATIVE_MARKETING_SOURCES: NonNativeMarketingSource[] = ['BigQuery']
export const VALID_SELF_MANAGED_MARKETING_SOURCES: ManualLinkSourceType[] = [
    'aws',
    'google-cloud',
    'cloudflare-r2',
    'azure',
]

export const MAX_ITEMS_TO_SHOW = 3

export const GOOGLE_ADS_CAMPAIGN_TABLE_NAME = 'campaign'
export const GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME = 'campaign_stats'

export const NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS: Record<NativeMarketingSource, string[]> = {
    GoogleAds: [GOOGLE_ADS_CAMPAIGN_TABLE_NAME, GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME],
    MetaAds: [], // TODO: Add required fields when MetaAds cost tile is implemented in MarketingDashboardMapper
}

export function MarketingDashboardMapper(source: NativeSource): DataWarehouseNode | null {
    switch (source.source.source_type) {
        case 'GoogleAds':
            return googleAdsCostTile(source)
        case 'MetaAds':
            // TODO: Implement MetaAds cost tile when MetaAds support is added
            return null
        default:
            return null
    }
}

export const COST_MICROS_MULTIPLIER = 1 / 1000000
