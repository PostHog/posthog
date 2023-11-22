import clsx from 'clsx'
import { getKeyMapping } from 'lib/taxonomy'
import { getDisplayNameFromEntityFilter, isAllEventsEntityFilter } from 'scenes/insights/utils'

import { ActionFilter, EntityFilter } from '~/types'

interface EntityFilterInfoProps {
    filter: EntityFilter | ActionFilter
    allowWrap?: boolean
    showSingleName?: boolean
    style?: React.CSSProperties
}

export function EntityFilterInfo({
    filter,
    allowWrap = false,
    showSingleName = false,
    style,
}: EntityFilterInfoProps): JSX.Element {
    if (isAllEventsEntityFilter(filter) && !filter?.custom_name) {
        return (
            <div className="EntityFilterInfo whitespace-nowrap max-w-100" title="All events">
                All events
            </div>
        )
    }

    const title = getDisplayNameFromEntityFilter(filter, false)
    const titleToDisplay = getKeyMapping(title, 'event')?.label?.trim() ?? title ?? undefined

    // No custom name
    if (!filter?.custom_name) {
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <span className="flex items-center" style={style}>
                <div
                    className={clsx('EntityFilterInfo whitespace-nowrap max-w-100', !allowWrap && 'truncate')}
                    title={titleToDisplay}
                >
                    {titleToDisplay}
                </div>
            </span>
        )
    }

    // Display custom name first and action title as secondary
    const customTitle = getDisplayNameFromEntityFilter(filter, true)

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <span className="flex items-center" style={style}>
            <div
                className={clsx('EntityFilterInfo whitespace-nowrap max-w-100', !allowWrap && 'truncate')}
                title={customTitle ?? undefined}
            >
                {customTitle}
            </div>
            {!showSingleName && (
                <div
                    className={clsx('EntityFilterInfo whitespace-nowrap max-w-100 ml-1', !allowWrap && 'truncate')}
                    title={titleToDisplay}
                >
                    ({titleToDisplay})
                </div>
            )}
        </span>
    )
}
