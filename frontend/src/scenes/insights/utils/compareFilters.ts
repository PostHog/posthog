import { AnyFilterType } from '~/types'
import { objectCleanWithEmpty, objectsEqual } from 'lib/utils'

import { cleanFilters } from './cleanFilters'

/** clean filters so that we can check for semantic equality with a deep equality check */
const clean = (f: Partial<AnyFilterType>): Partial<AnyFilterType> => {
    // remove undefined values, empty array and empty objects
    const cleanedFilters = objectCleanWithEmpty(cleanFilters(f))

    cleanedFilters.events = cleanedFilters.events?.map((e) => {
        // event math `total` is the default
        if (e.math === 'total') {
            delete e.math
        }
        return e
    })
    return cleanedFilters
}

/** compares to filter objects for semantical equality */
export function compareFilters(a: Partial<AnyFilterType>, b: Partial<AnyFilterType>): boolean {
    // this is not optimized for speed and does not work for many cases yet
    // e.g. falsy values are not treated the same as undefined values, unset filters are not handled, ordering of series isn't checked
    return objectsEqual(clean(a), clean(b))
}
