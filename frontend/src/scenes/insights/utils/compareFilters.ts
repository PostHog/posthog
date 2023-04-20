import { AnyFilterType } from '~/types'
import { objectCleanWithEmpty, objectsEqual } from 'lib/utils'

import { cleanFilters } from './cleanFilters'

const clean = (f: Partial<AnyFilterType>): Partial<AnyFilterType> => objectCleanWithEmpty(cleanFilters(f))

/** compares to filter objects for semantical equality */
export function compareFilters(a: Partial<AnyFilterType>, b: Partial<AnyFilterType>): boolean {
    // this is not optimized for speed and does not work for many cases yet
    // e.g. falsy values are not treated the same as undefined values, unset filters are not handled, ordering of series isn't checked
    return objectsEqual(clean(a), clean(b))
}
