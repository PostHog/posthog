import { AnyFilterType } from '~/types'
import { objectCleanWithEmpty, objectsEqual } from 'lib/utils'

import { cleanFilters } from './cleanFilters'

/** clean filters so that we can check for semantic equality with a deep equality check */
const clean = (
    f: Partial<AnyFilterType>,
    test_account_filters_default_checked: boolean | undefined
): Partial<AnyFilterType> => {
    // remove undefined values, empty array and empty objects
    const cleanedFilters = objectCleanWithEmpty(cleanFilters(f, test_account_filters_default_checked))

    // do we need an order property on events or actions?
    const needsOrder = (cleanedFilters.events || []).length + (cleanedFilters.actions || []).length > 1

    cleanedFilters.events?.forEach((e) => {
        // event math `total` is the default
        if (e.math === 'total') {
            delete e.math
        }

        // delete unnecessary event order
        if (!needsOrder) {
            delete e.order
        }
    })

    cleanedFilters.actions?.forEach((a) => {
        // delete unnecessary action order
        if (!needsOrder) {
            delete a.order
        }
    })

    // used only for persons endpoint
    delete f.entity_type

    return cleanedFilters
}

/** compares to filter objects for semantical equality */
export function compareFilters(
    a: Partial<AnyFilterType>,
    b: Partial<AnyFilterType>,
    test_account_filters_default_checked: boolean | undefined
): boolean {
    // this is not optimized for speed and does not work for many cases yet
    // e.g. falsy values are not treated the same as undefined values, unset filters are not handled, ordering of series isn't checked
    return objectsEqual(clean(a, test_account_filters_default_checked), clean(b, test_account_filters_default_checked))
}
