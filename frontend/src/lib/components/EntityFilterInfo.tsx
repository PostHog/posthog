import clsx from 'clsx'

import { getDisplayNameFromEntityFilter, isAllEventsEntityFilter } from 'scenes/insights/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { ActionFilter, EntityFilter } from '~/types'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

interface EntityFilterInfoProps {
    filter: EntityFilter | ActionFilter
    allowWrap?: boolean
    showSingleName?: boolean
    style?: React.CSSProperties
    filterGroupType?: TaxonomicFilterGroupType
    isOptional?: boolean
}

export function EntityFilterInfo({
    filter,
    allowWrap = false,
    showSingleName = false,
    style,
    filterGroupType,
    isOptional = false,
}: EntityFilterInfoProps): JSX.Element {
    if (isAllEventsEntityFilter(filter) && !filter?.custom_name) {
        return (
            <span
                className={clsx('EntityFilterInfo max-w-100', !allowWrap && 'whitespace-nowrap truncate')}
                title="All events"
            >
                All events
                {isOptional && <span className="ml-1 text-xs font-normal text-secondary normal-case">(optional)</span>}
            </span>
        )
    }

    const title = getDisplayNameFromEntityFilter(filter, false)
    const titleToDisplay =
        (filterGroupType ? getCoreFilterDefinition(title, filterGroupType)?.label?.trim() : null) ?? title ?? undefined

    // No custom name
    if (!filter?.custom_name) {
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <span className={!allowWrap ? 'flex truncate  items-center' : ''} style={style}>
                <span
                    className={clsx('EntityFilterInfo max-w-100', !allowWrap && 'whitespace-nowrap truncate')}
                    title={titleToDisplay}
                >
                    {titleToDisplay}
                </span>
                {isOptional && <span className="ml-1 text-xs font-normal text-secondary normal-case">(optional)</span>}
            </span>
        )
    }

    // Display custom name first and action title as secondary
    const customTitle = getDisplayNameFromEntityFilter(filter, true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span className={!allowWrap ? 'flex items-baseline' : ''} style={style}>
            <span
                className={clsx('EntityFilterInfo max-w-100', !allowWrap && 'whitespace-nowrap truncate')}
                title={customTitle ?? undefined}
            >
                {customTitle}
            </span>
            {isOptional && <span className="ml-1 text-xs font-normal text-secondary normal-case">(optional)</span>}
            {!showSingleName && (
                <span
                    className={clsx(
                        'EntityFilterInfo max-w-100 ml-1 text-secondary text-xs',
                        !allowWrap && 'whitespace-nowrap truncate'
                    )}
                    title={titleToDisplay}
                >
                    {titleToDisplay}
                </span>
            )}
        </span>
    )
}
