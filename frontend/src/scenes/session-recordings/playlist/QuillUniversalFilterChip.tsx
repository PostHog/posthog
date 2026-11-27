import { useValues } from 'kea'

import { IconLogomark } from '@posthog/icons'
import { Chip, ChipClose } from '@posthog/quill'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { PropertyFilterIcon } from 'lib/components/PropertyFilters/components/PropertyFilterIcon'
import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import {
    isActionFilter,
    isEntityFilter,
    isEventFilter,
    isFeatureFlagFilter,
} from 'lib/components/UniversalFilters/utils'
import { midEllipsis } from 'lib/utils/strings'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, UniversalFilterValue } from '~/types'

function PropertyLabel({ filter }: { filter: AnyPropertyFilter }): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)

    let label = formatPropertyLabel(
        filter,
        cohortsById,
        (s) => formatPropertyValueForDisplay(filter.key, s)?.toString() || '?'
    )
    const isEventFeature = label.startsWith('$feature/')
    if (isEventFeature) {
        label = label.replace('$feature/', 'Feature: ')
    }
    return (
        <>
            <span className="shrink-0 text-muted-foreground">
                {isEventFeature ? <IconLogomark /> : <PropertyFilterIcon type={filter.type} />}
            </span>
            <span className="truncate" title={label}>
                {midEllipsis(label, 32)}
            </span>
        </>
    )
}

/** A removable chip for one property, event, action or feature flag filter of the recordings list. */
export function QuillUniversalFilterChip({
    filter,
    onClose,
}: {
    filter: UniversalFilterValue
    onClose: () => void
}): JSX.Element {
    return (
        <Chip className="max-w-60 ph-no-capture" data-attr="list-filter-chip">
            {isEntityFilter(filter) && filter.negation && (
                <span className="shrink-0 text-muted-foreground">did not perform</span>
            )}
            {isEventFilter(filter) || isActionFilter(filter) ? (
                <span className="truncate">
                    <EntityFilterInfo filter={filter} />
                </span>
            ) : isFeatureFlagFilter(filter) ? (
                <span className="truncate">{filter.key}</span>
            ) : (
                <PropertyLabel filter={filter} />
            )}
            <ChipClose onClick={onClose} aria-label="Remove filter" />
        </Chip>
    )
}
