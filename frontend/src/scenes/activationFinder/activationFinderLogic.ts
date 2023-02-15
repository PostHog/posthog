import { kea } from 'kea'
import { convertPropertyGroupToProperties } from 'lib/utils'
import { AnyPropertyFilter, EmptyPropertyFilter, PropertyGroupFilter } from '~/types'

import type { activationFinderLogicType } from './activationFinderLogicType'

const normalizeProperties = (
    propertyFilters: AnyPropertyFilter | AnyPropertyFilter[] | PropertyGroupFilter
): {
    propertyFilters: AnyPropertyFilter[]
} => {
    // there seem to be multiple representations of "empty" properties
    // the page does not work with some of those representations
    // this action normalises them
    if (Array.isArray(propertyFilters)) {
        if (propertyFilters.length === 0) {
            return { propertyFilters: [{} as EmptyPropertyFilter] }
        } else {
            return { propertyFilters }
        }
    } else {
        return { propertyFilters: [propertyFilters as EmptyPropertyFilter] }
    }
}

export const activationFinderLogic = kea<activationFinderLogicType>({
    path: ['scenes', 'activationFinder', 'activationFinderLogic'],
    actions: () => ({
        setInitialEvent: (event: string) => ({ event }),
        setInitialPropertyFilters: (
            propertyFilters: AnyPropertyFilter[] | AnyPropertyFilter | PropertyGroupFilter
        ): {
            propertyFilters: AnyPropertyFilter[]
        } => {
            return normalizeProperties(propertyFilters)
        },
        setFinalEvent: (event: string) => ({ event }),
        setFinalPropertyFilters: (
            propertyFilters: AnyPropertyFilter[] | AnyPropertyFilter | PropertyGroupFilter
        ): {
            propertyFilters: AnyPropertyFilter[]
        } => {
            return normalizeProperties(propertyFilters)
        },
    }),
    reducers: () => ({
        initialEvent: [
            '' as string,
            {
                setInitialEvent: (_, { event }) => event,
            },
        ],
        initialPropertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setInitialPropertyFilters: (_, { propertyFilters }) =>
                    convertPropertyGroupToProperties(propertyFilters) as AnyPropertyFilter[],
            },
        ],
        finalEvent: [
            '' as string,
            {
                setFinalEvent: (_, { event }) => event,
            },
        ],
        finalPropertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setFinalPropertyFilters: (_, { propertyFilters }) =>
                    convertPropertyGroupToProperties(propertyFilters) as AnyPropertyFilter[],
            },
        ],
    }),
})
