import clsx from 'clsx'

import { getEventDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { getDisplayNameFromEntityFilter, isAllEventsEntityFilter } from 'scenes/insights/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { ActionFilter, EntityFilter, EntityTypes } from '~/types'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

interface EntityFilterInfoProps {
    filter: EntityFilter | ActionFilter
    allowWrap?: boolean
    showSingleName?: boolean
    style?: React.CSSProperties
    filterGroupType?: TaxonomicFilterGroupType
    isOptional?: boolean
    showIcon?: boolean
}

export function EntityFilterInfo({
    filter,
    allowWrap = false,
    showSingleName = false,
    style,
    filterGroupType,
    isOptional = false,
    showIcon = false,
}: EntityFilterInfoProps): JSX.Element {
    const icon = showIcon ? (
        <span className="inline-flex shrink-0 text-base">
            {getEventDefinitionIcon({
                id: String(filter.id ?? ''),
                name: filter.name || String(filter.id ?? ''),
                is_action: filter.type === EntityTypes.ACTIONS,
            })}
        </span>
    ) : null

    if (isAllEventsEntityFilter(filter) && !filter?.custom_name) {
        return (
            <span className={!allowWrap ? 'flex truncate items-center gap-1' : ''}>
                {icon}
                <span
                    className={clsx('EntityFilterInfo max-w-100', !allowWrap && 'whitespace-nowrap truncate')}
                    title="All events"
                >
                    All events
                </span>
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
            <span className={!allowWrap ? 'flex truncate items-center gap-1' : ''} style={style}>
                {icon}
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
        <span className={!allowWrap ? 'flex items-center gap-1' : ''} style={style}>
            {icon}
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
