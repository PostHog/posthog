import Ajv from 'ajv'

import {
    CompareFilter,
    RevenueAnalyticsPropertyFilters,
    WebAnalyticsPropertyFilters,
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, SessionPropertyFilter } from '~/types'

import schema from './schema.json'

const ajv = new Ajv({ allowUnionTypes: true })
ajv.addSchema(schema)

export const isAnyPropertyFilters = (data: unknown): data is AnyPropertyFilter[] => {
    const validator = ajv.getSchema('#/definitions/AnyPropertyFilter')
    if (!validator) {
        throw new Error('Could not find validator for AnyPropertyFilter')
    }
    if (!Array.isArray(data)) {
        return false
    }
    return data.every((item) => validator(item))
}

export const isWebAnalyticsPropertyFilters = (data: unknown): data is WebAnalyticsPropertyFilters => {
    const validator = ajv.getSchema('#/definitions/WebAnalyticsPropertyFilters')
    if (!validator) {
        throw new Error('Could not find validator for WebAnalyticsPropertyFilters')
    }
    return validator(data) as boolean
}

export const isRevenueAnalyticsPropertyFilters = (data: unknown): data is RevenueAnalyticsPropertyFilters => {
    const validator = ajv.getSchema('#/definitions/RevenueAnalyticsPropertyFilters')
    if (!validator) {
        throw new Error('Could not find validator for RevenueAnalyticsPropertyFilters')
    }
    return validator(data) as boolean
}

export const isSessionPropertyFilters = (data: unknown): data is SessionPropertyFilter[] => {
    const validator = ajv.getSchema('#/definitions/SessionPropertyFilter')
    if (!validator) {
        throw new Error('Could not find validator for SessionPropertyFilter')
    }
    if (!Array.isArray(data)) {
        return false
    }
    return data.every((item) => validator(item))
}

export const isCompareFilter = (data: unknown): data is CompareFilter => {
    const validator = ajv.getSchema('#/definitions/CompareFilter')
    if (!validator) {
        throw new Error('Could not find validator for CompareFilter')
    }
    return validator(data) as boolean
}
