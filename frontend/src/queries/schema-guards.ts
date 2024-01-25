import Ajv from 'ajv'

import { WebAnalyticsPropertyFilters } from '~/queries/schema'

import schema from './schema.json'
const ajv = new Ajv()
ajv.addSchema(schema)

export const isWebAnalyticsPropertyFilters = (data: unknown): data is WebAnalyticsPropertyFilters => {
    const validator = ajv.getSchema('#/definitions/WebAnalyticsPropertyFilters')
    if (!validator) {
        throw new Error('Could not find validator for WebAnalyticsPropertyFilters')
    }
    return validator(data) as boolean
}
