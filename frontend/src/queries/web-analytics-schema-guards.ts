import { CompareFilter, WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'

import * as validators from './web-analytics-validators.js'

export const isWebAnalyticsPropertyFilters = (data: unknown): data is WebAnalyticsPropertyFilters => {
    return validators.WebAnalyticsPropertyFilters(data) as boolean
}

export const isCompareFilter = (data: unknown): data is CompareFilter => {
    return validators.CompareFilter(data) as boolean
}
