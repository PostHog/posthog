import Ajv from 'ajv'

import { WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, SessionPropertyFilter } from '~/types'

import schema from './schema.json'
const ajv = new Ajv({
    allowUnionTypes: true,
})
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
