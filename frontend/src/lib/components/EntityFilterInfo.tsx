import clsx from 'clsx'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ensureStringIsNotBlank } from 'lib/utils/strings'
import { getEventDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { formatEventName, getDisplayNameFromEntityFilter, isAllEventsEntityFilter } from 'scenes/insights/utils'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { ActionFilter, EntityFilter, EntityTypes } from '~/types'

import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

export interface UnderlyingEntity {
    /** The raw key the filter queries: event name as sent, action name, or table name. */
    raw: string
    /** Human-readable form of the raw key (core event labels applied). */
    display: string
    kind: 'event' | 'events' | 'action' | 'data warehouse table'
}

/**
 * The concrete thing a series filter queries, independent of any renames on the series.
 * A series can be renamed via `custom_name` or by overriding `name` directly (e.g. via the
 * API), so neither of those fields reliably reveals what is actually being queried.
 */
export function getUnderlyingEntity(filter: EntityFilter | ActionFilter): UnderlyingEntity | null {
    if (filter.type === EntityTypes.ACTIONS) {
        const raw = ensureStringIsNotBlank(filter.name) ?? (filter.id != null ? String(filter.id) : null)
        return raw ? { raw, display: raw, kind: 'action' } : null
    }
    if (filter.type === EntityTypes.DATA_WAREHOUSE) {
        const tableName =
            'table_name' in filter && typeof filter.table_name === 'string'
                ? ensureStringIsNotBlank(filter.table_name)
                : null
        const raw = tableName ?? (typeof filter.id === 'string' ? ensureStringIsNotBlank(filter.id) : null)
        return raw ? { raw, display: raw, kind: 'data warehouse table' } : null
    }
    if (filter.type === EntityTypes.GROUPS) {
        // Inline event groups hold their comma-separated event keys in `name`
        const raw = ensureStringIsNotBlank(filter.name)
        return raw ? { raw, display: formatEventName(raw) ?? raw, kind: raw.includes(',') ? 'events' : 'event' } : null
    }
    // Events — filters without an explicit type are events by convention
    if (typeof filter.id === 'string' && filter.id) {
        return { raw: filter.id, display: formatEventName(filter.id) ?? filter.id, kind: 'event' }
    }
    return null
}

export interface EntityFilterDisplayInfo {
    /** The label users see for the series: `custom_name`, falling back to `name`/`id`. */
    displayName?: string
    underlying: UnderlyingEntity | null
    /** True when the label alone doesn't reveal the underlying entity. */
    isRenamed: boolean
}

export function getEntityFilterDisplayInfo(
    filter: EntityFilter | ActionFilter,
    filterGroupType?: TaxonomicFilterGroupType
): EntityFilterDisplayInfo {
    let name: string | undefined
    if (isAllEventsEntityFilter(filter) && !filter?.custom_name) {
        name = 'All events'
    } else {
        const raw = getDisplayNameFromEntityFilter(filter, false)
        name =
            (filterGroupType ? getCoreFilterDefinition(raw, filterGroupType)?.label?.trim() : null) ?? raw ?? undefined
    }
    const customName = filter?.custom_name ? (getDisplayNameFromEntityFilter(filter, true) ?? undefined) : undefined
    const displayName = customName ?? name
    const underlying = getUnderlyingEntity(filter)
    return {
        displayName,
        underlying,
        isRenamed: !!displayName && !!underlying && underlying.display !== displayName,
    }
}

export function EntityFilterInfoTooltipTitle({
    displayName,
    underlying,
}: {
    displayName: string
    underlying: UnderlyingEntity | null
}): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="font-semibold">{displayName}</span>
            {underlying &&
                underlying.raw !== displayName &&
                (underlying.kind === 'event' || underlying.kind === 'events' ? (
                    <span>
                        {underlying.kind === 'events' ? 'Events sent as' : 'Event sent as'}{' '}
                        <code>{underlying.raw}</code>
                    </span>
                ) : underlying.kind === 'action' ? (
                    <span>Action: {underlying.raw}</span>
                ) : (
                    <span>
                        Data warehouse table: <code>{underlying.raw}</code>
                    </span>
                ))}
        </div>
    )
}

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
    const { displayName, underlying } = getEntityFilterDisplayInfo(filter, filterGroupType)

    // Only reveal the underlying entity when the label doesn't already show it.
    const underlyingName = underlying && underlying.display !== displayName ? underlying.display : undefined
    const showTooltip = !!displayName && !!underlying && underlying.raw !== displayName

    const icon = showIcon
        ? getEventDefinitionIcon({
              id: String(filter.id ?? ''),
              name: filter.name || String(filter.id ?? ''),
              is_action: filter.type === EntityTypes.ACTIONS,
              is_data_warehouse: filter.type === EntityTypes.DATA_WAREHOUSE,
          })
        : null

    const content = (
        // eslint-disable-next-line react/forbid-dom-props
        <span
            className={clsx(
                isColumn
                    ? 'flex flex-col items-start gap-0.5'
                    : !allowWrap && 'block overflow-hidden text-ellipsis whitespace-nowrap'
            )}
            style={style}
        >
            <span className={clsx(icon && 'inline-flex items-center gap-1 max-w-full')}>
                {icon}
                <span
                    className={clsx('EntityFilterInfo max-w-full', !allowWrap && 'whitespace-nowrap truncate')}
                    title={showTooltip ? undefined : displayName}
                >
                    {displayName}
                </span>
            </span>
            {isOptional && (
                <span className={clsx('text-xs font-normal text-secondary normal-case', !isColumn && 'ml-1')}>
                    (optional)
                </span>
            )}
            {underlyingName && !showSingleName && (
                <span
                    className={clsx(
                        'EntityFilterInfo max-w-full text-secondary text-xs',
                        isColumn ? (icon ? 'ml-5' : '') : 'ml-1',
                        !allowWrap && 'whitespace-nowrap truncate'
                    )}
                    title={showTooltip ? undefined : underlyingName}
                >
                    {underlyingName}
                </span>
            )}
        </span>
    )

    if (!showTooltip || !displayName) {
        return content
    }
    return (
        <Tooltip title={<EntityFilterInfoTooltipTitle displayName={displayName} underlying={underlying} />}>
            {content}
        </Tooltip>
    )
}
