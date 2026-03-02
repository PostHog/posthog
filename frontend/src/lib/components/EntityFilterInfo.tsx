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
    let name: string | undefined
    if (isAllEventsEntityFilter(filter) && !filter?.custom_name) {
        name = 'All events'
    } else {
        const raw = getDisplayNameFromEntityFilter(filter, false)
        name =
            (filterGroupType ? getCoreFilterDefinition(raw, filterGroupType)?.label?.trim() : null) ?? raw ?? undefined
    }

    const customName = filter?.custom_name ? (getDisplayNameFromEntityFilter(filter, true) ?? undefined) : undefined

    const icon = showIcon
        ? getEventDefinitionIcon({
              id: String(filter.id ?? ''),
              name: filter.name || String(filter.id ?? ''),
              is_action: filter.type === EntityTypes.ACTIONS,
          })
        : null

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span className={!allowWrap ? 'flex truncate items-center gap-1' : ''} style={style}>
            {icon}
            <span
                className={clsx('EntityFilterInfo max-w-100', !allowWrap && 'whitespace-nowrap truncate')}
                title={customName ?? name}
            >
                {customName ?? name}
            </span>
            {isOptional && <span className="ml-1 text-xs font-normal text-secondary normal-case">(optional)</span>}
            {customName && !showSingleName && (
                <span
                    className={clsx(
                        'EntityFilterInfo max-w-100 ml-1 text-secondary text-xs',
                        !allowWrap && 'whitespace-nowrap truncate'
                    )}
                    title={name}
                >
                    {name}
                </span>
            )}
        </span>
    )
}
