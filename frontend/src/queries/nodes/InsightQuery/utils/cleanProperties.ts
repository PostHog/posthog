import {
    AnyPropertyFilter,
    EventPropertyFilter,
    PropertyFilterType,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PropertyOperator,
} from '~/types'

/** Cleans properties of insights. These are either a simple list of property filters or a property group filter. The property group filter has
 * a type (AND, OR) and a list of values that are property group filter values, which are either property group filter values or a simple list of
 * property filters.
 */
export const cleanGlobalProperties = (
    properties: Record<string, any> | Record<string, any>[] | undefined
): AnyPropertyFilter[] | PropertyGroupFilter | undefined => {
    if (
        properties == undefined ||
        (Array.isArray(properties) && properties.length == 0) ||
        Object.keys(properties).length == 0
    ) {
        // empty properties
        return undefined
    } else if (isOldStyleProperties(properties)) {
        // old style properties
        properties = transformOldStyleProperties(properties)
        properties = {
            type: 'AND',
            values: [{ type: 'AND', values: properties }],
        }
        return cleanPropertyGroupFilter(properties)
    } else if (Array.isArray(properties)) {
        // list of property filters
        properties = {
            type: 'AND',
            values: [{ type: 'AND', values: properties }],
        }
        return cleanPropertyGroupFilter(properties)
    } else if (
        (properties['type'] === 'AND' || properties['type'] === 'OR') &&
        !properties['values'].some((property: any) => property['type'] === 'AND' || property['type'] === 'OR')
    ) {
        // property group filter value
        properties = {
            type: 'AND',
            values: [properties],
        }
        return cleanPropertyGroupFilter(properties)
    }
    // property group filter
    return cleanPropertyGroupFilter(properties)
}

/** Cleans properties of entities i.e. event and action nodes. These are a simple list of property filters. */
export const cleanEntityProperties = (
    properties: Record<string, any> | Record<string, any>[] | undefined
): AnyPropertyFilter[] | undefined => {
    if (
        properties == undefined ||
        (Array.isArray(properties) && properties.length == 0) ||
        Object.keys(properties).length == 0
    ) {
        // empty properties
        return undefined
    } else if (isOldStyleProperties(properties)) {
        // old style properties
        return transformOldStyleProperties(properties)
    } else if (Array.isArray(properties)) {
        // list of property filters
        return properties.map(cleanProperty)
    } else if (
        (properties['type'] === 'AND' || properties['type'] === 'OR') &&
        !properties['values'].some((property: any) => property['type'] === 'AND' || property['type'] === 'OR')
    ) {
        // property group filter value
        return properties.values.map(cleanProperty)
    }
    throw new Error('Unexpected format of entity properties.')
}

const cleanPropertyGroupFilter = (properties: Record<string, any>): PropertyGroupFilter => {
    properties['values'] = cleanPropertyGroupFilterValues(properties.values)
    return properties as PropertyGroupFilter
}

const cleanPropertyGroupFilterValues = (
    properties: (AnyPropertyFilter | PropertyGroupFilterValue)[]
): (AnyPropertyFilter | PropertyGroupFilterValue)[] => {
    return properties.map(cleanPropertyGroupFilterValue)
}

const cleanPropertyGroupFilterValue = (
    property: AnyPropertyFilter | PropertyGroupFilterValue
): AnyPropertyFilter | PropertyGroupFilterValue => {
    if (property['type'] == 'AND' || property['type'] == 'OR') {
        // property group filter value
        property['values'] = cleanPropertyGroupFilterValues(property['values'] as PropertyGroupFilterValue[])
        return property
    }
    // property filter
    return cleanProperty(property)
}

const cleanProperty = (property: Record<string, any>): AnyPropertyFilter => {
    if (Object.keys(property).length === 0) {
        return { type: PropertyFilterType.HogQL, key: 'true' }
    }

    // remove invalid properties without type
    if (property['type'] === undefined) {
        return { type: PropertyFilterType.HogQL, key: 'true' }
    }

    // fix type typo
    if (property['type'] === 'events') {
        property['type'] = 'event'
    }

    // fix value key typo
    if (property['values'] !== undefined && property['value'] === undefined) {
        property['value'] = property['values']
        delete property['values']
    }

    // convert precalculated and static cohorts to cohorts
    if (['precalculated-cohort', 'static-cohort'].includes(property['type'])) {
        property['type'] = 'cohort'
    }

    // fix invalid property key for cohorts
    if (property['type'] === 'cohort' && property['key'] !== 'id') {
        property['key'] = 'id'
    }

    // set a default operator for properties that support it, but don't have an operator set
    if (isPropertyWithOperator(property) && property['operator'] === undefined) {
        property['operator'] = 'exact'
    }

    // remove the operator for properties that don't support it, but have it set
    if (!isPropertyWithOperator(property) && property['operator'] !== undefined) {
        delete property['operator']
    }

    // convert `negation` for cohorts
    if (property['type'] === 'cohort' && property['negation'] !== undefined) {
        if (property['operator'] === PropertyOperator.Exact && property['negation']) {
            property['operator'] = PropertyOperator.NotIn
        }
        delete property['negation']
    }

    // remove none from values
    if (Array.isArray(property['value'])) {
        property['value'] = property['value'].filter((x) => x !== null)
    }

    // remove keys without concrete value
    Object.keys(property).forEach((key) => {
        if (property[key] === undefined) {
            delete property[key]
        }
    })

    return property
}

const isPropertyWithOperator = (property: Record<string, any>): boolean => {
    return !['hogql'].includes(property['type'])
}

// old style dict properties e.g. {"utm_medium__icontains": "email"}
const isOldStyleProperties = (properties: Record<string, any> | Record<string, any>[]): boolean => {
    return (
        !Array.isArray(properties) && Object.keys(properties).length === 1 && !['AND', 'OR'].includes(properties.type)
    )
}

const transformOldStyleProperties = (
    properties: Record<string, any> | Record<string, any>[]
): EventPropertyFilter[] => {
    const key = Object.keys(properties)[0]
    const value = Object.values(properties)[0]
    const keySplit = key.split('__')

    return [
        {
            key: keySplit[0],
            value: value,
            operator: keySplit.length > 1 ? (keySplit[1] as PropertyOperator) : PropertyOperator.Exact,
            type: PropertyFilterType.Event,
        },
    ]
}
