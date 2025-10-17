import {
    CompareFilter,
    RevenueAnalyticsPropertyFilters,
    WebAnalyticsPropertyFilters,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, SessionPropertyFilter } from '~/types'

import * as validators from './validators.js'

export const isAnyPropertyFilters = (data: unknown): data is AnyPropertyFilter[] => {
    if (!Array.isArray(data)) {
        return false
    }
    return data.every((item) => validators.AnyPropertyFilter(item))
}

export const isWebAnalyticsPropertyFilters = (data: unknown): data is WebAnalyticsPropertyFilters => {
    return validators.WebAnalyticsPropertyFilters(data) as boolean
}

export const isRevenueAnalyticsPropertyFilters = (data: unknown): data is RevenueAnalyticsPropertyFilters => {
    return validators.RevenueAnalyticsPropertyFilters(data) as boolean
}

export const isSessionPropertyFilters = (data: unknown): data is SessionPropertyFilter[] => {
    if (!Array.isArray(data)) {
        return false
    }
    return data.every((item) => validators.SessionPropertyFilter(item))
}

export const isCompareFilter = (data: unknown): data is CompareFilter => {
    return validators.CompareFilter(data) as boolean
}
