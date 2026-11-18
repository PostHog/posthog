import {
    ExperimentMetric,
    // eslint-disable-next-line import/no-cycle
} from '~/queries/schema/schema-general'
import { AnyPropertyFilter, SessionPropertyFilter } from '~/types'

import * as validators from './validators.js'

export const isAnyPropertyFilters = (data: unknown): data is AnyPropertyFilter[] => {
    if (!Array.isArray(data)) {
        return false
    }
    return data.every((item) => validators.AnyPropertyFilter(item))
}

export const isSessionPropertyFilters = (data: unknown): data is SessionPropertyFilter[] => {
    if (!Array.isArray(data)) {
        return false
    }
    return data.every((item) => validators.SessionPropertyFilter(item))
}

export const isExperimentMetric = (data: unknown): data is ExperimentMetric => {
    return validators.ExperimentMetric(data) as boolean
}
