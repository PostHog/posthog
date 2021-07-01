import { AnyPropertyFilter, PropertyFilter, PropertyOperator } from '~/types'

export function parseProperties(
    input: AnyPropertyFilter[] | Record<string, string> | null | undefined
): AnyPropertyFilter[] {
    if (Array.isArray(input) || !input) {
        return input || []
    }
    // Old style dict properties
    return Object.entries(input).map(([inputKey, value]) => {
        const [key, operator] = inputKey.split('__')
        return {
            key,
            value,
            operator: operator as PropertyOperator,
            type: 'event',
        }
    })
}

/** Checks if the AnyPropertyFilter is a filled PropertyFilter */
export function isValidPropertyFilter(filter: AnyPropertyFilter): filter is PropertyFilter {
    return (
        !!filter && // is not falsy
        'key' in filter && // has a "key" property
        Object.values(filter).some((v) => !!v) // contains some properties with values
    )
}
