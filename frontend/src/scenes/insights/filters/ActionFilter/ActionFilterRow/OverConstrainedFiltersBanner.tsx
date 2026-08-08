import { LemonBanner } from '@posthog/lemon-ui'

import { findOverConstrainedPropertyKeys } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter } from '~/types'

export function OverConstrainedFiltersBanner({
    properties,
}: {
    properties?: AnyPropertyFilter[] | null
}): JSX.Element | null {
    if (findOverConstrainedPropertyKeys(properties).length === 0) {
        return null
    }

    return (
        <LemonBanner type="info" className="mt-2">
            These filters check the same property, so they combine with AND and one event must match all of them. To
            match any of several values instead, put them in a single filter, or use a filter group.
        </LemonBanner>
    )
}
