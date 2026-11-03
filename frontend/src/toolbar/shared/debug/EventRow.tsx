import clsx from 'clsx'

import { IconChevronDown, IconCopy, IconPin, IconPinFilled } from '@posthog/icons'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'

import { classifyEvent, EventCategory } from '~/toolbar/shared/debug/eventCategories'
import { EventType } from '~/types'

const EVENT_CATEGORY_COLORS: Record<EventCategory, string> = {
    posthog: '#5375FF',
    custom: '#43B573',
    snapshot: '#F1A82C',
}

function EventTimestamp({ e, relative }: { e: EventType; relative?: boolean }): JSX.Element {
    const ts = dayjs(e.timestamp)

    if (relative) {
        return <span className="whitespace-nowrap">{ts.fromNow()}</span>
    }

    let formatString = 'HH:mm:ss'
    if (!ts.isSame(dayjs(), 'day')) {
        formatString = 'ddd HH:mm:ss'
    }

    return (
        <span className="whitespace-nowrap">
            <span>{ts.format(formatString)}</span>
            <span className="text-xxs text-secondary">{ts.format('.SSS')}</span>
        </span>
    )
}

function EventCategoryDot({ category }: { category: EventCategory }): JSX.Element {
    return (
        <span
            className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: EVENT_CATEGORY_COLORS[category] }}
        />
    )
}

export function EventRow({
    e,
    expanded,
    isPinned,
    expandedProperties,
    searchText,
    relativeTimestamps,
    onToggleExpand,
    onTogglePin,
}: {
    e: EventType
    expanded: boolean
    isPinned: boolean
    expandedProperties: any
    searchText: string
    relativeTimestamps: boolean
    onToggleExpand: () => void
    onTogglePin: (eventId: string) => void
}): JSX.Element {
    const category = classifyEvent(e)

    const handleCopyPayload = (ev: React.MouseEvent): void => {
        ev.stopPropagation()
        const payload = { event: e.event, timestamp: e.timestamp, properties: e.properties, uuid: e.uuid }
        void navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    }

    return (
        <div
            className={clsx('group/row -mx-1 py-1 px-2 cursor-pointer rounded', isPinned && 'bg-surface-primary')}
            onClick={onToggleExpand}
        >
            <div className="flex flex-row justify-between items-center gap-2">
                <div className="flex flex-row items-center gap-1.5 min-w-0">
                    <EventCategoryDot category={category} />
                    <span className="truncate font-medium text-sm">
                        <PropertyKeyInfo disableIcon value={e.event} type={TaxonomicFilterGroupType.Events} />
                    </span>
                </div>

                <div className="flex flex-row items-center gap-1 shrink-0">
                    <button
                        className={clsx(
                            'flex items-center justify-center cursor-pointer',
                            isPinned ? 'opacity-100' : 'opacity-0 group-hover/row:opacity-100'
                        )}
                        onClick={(ev) => {
                            ev.stopPropagation()
                            if (e.uuid) {
                                onTogglePin(e.uuid)
                            }
                        }}
                        title={isPinned ? 'Unpin event' : 'Pin event'}
                    >
                        {isPinned ? (
                            <IconPinFilled className="text-warning text-sm" />
                        ) : (
                            <IconPin className="text-secondary text-sm" />
                        )}
                    </button>
                    <EventTimestamp e={e} relative={relativeTimestamps} />
                    <IconChevronDown className={clsx('text-secondary text-sm', expanded ? 'rotate-180' : '')} />
                </div>
            </div>
            {expanded && (
                <div className="my-1 ml-1 pl-2 border-l-2">
                    <div className="flex justify-end mb-1">
                        <button
                            className="flex items-center gap-1 text-xxs text-secondary cursor-pointer hover:text-primary"
                            onClick={handleCopyPayload}
                            title="Copy event payload as JSON"
                        >
                            <IconCopy className="text-xs" />
                            Copy payload
                        </button>
                    </div>
                    <SimpleKeyValueList
                        item={expandedProperties}
                        emptyMessage={searchText ? 'No matching properties' : 'No properties'}
                    />
                </div>
            )}
        </div>
    )
}
