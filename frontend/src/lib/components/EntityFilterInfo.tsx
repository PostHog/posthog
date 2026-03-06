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
    layout?: 'row' | 'column'
    filterGroupType?: TaxonomicFilterGroupType
    isOptional?: boolean
    showIcon?: boolean
}

export function EntityFilterInfo({
    filter,
    allowWrap = false,
    showSingleName = false,
    style,
    layout = 'row',
    filterGroupType,
    isOptional = false,
    showIcon = false,
}: EntityFilterInfoProps): JSX.Element {
    const isColumn = layout === 'column'
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
        <span
            className={clsx(
                !allowWrap && 'truncate',
                isColumn ? 'flex flex-col items-start gap-0.5' : !allowWrap && 'flex items-center gap-1'
            )}
            style={style}
        >
            <span className={clsx(icon && 'inline-flex items-center gap-1')}>
                {icon}
                <span
                    className={clsx('EntityFilterInfo max-w-100', !allowWrap && 'whitespace-nowrap truncate')}
                    title={customName ?? name}
                >
                    {customName ?? name}
                </span>
            </span>
            {isOptional && (
                <span className={clsx('text-xs font-normal text-secondary normal-case', !isColumn && 'ml-1')}>
                    (optional)
                </span>
            )}
            {customName && !showSingleName && (
                <span
                    className={clsx(
                        'EntityFilterInfo max-w-100 text-secondary text-xs',
                        isColumn ? (icon ? 'ml-5' : '') : 'ml-1',
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
