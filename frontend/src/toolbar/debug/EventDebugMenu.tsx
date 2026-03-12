import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import {
    BaseIcon,
    IconCheck,
    IconChevronDown,
    IconClock,
    IconCopy,
    IconDownload,
    IconEye,
    IconHide,
    IconLogomark,
    IconPause,
    IconPin,
    IconPinFilled,
    IconPlay,
    IconTrash,
    IconVideoCamera,
    IconX,
} from '@posthog/icons'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SimpleKeyValueList } from 'lib/components/SimpleKeyValueList'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { IconUnverifiedEvent } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SettingsBar, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { classifyEvent, EventCategory, eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'
import { EventType } from '~/types'

import { ToolbarMenu } from '../bar/ToolbarMenu'

const EVENT_CATEGORY_COLORS: Record<EventCategory, string> = {
    posthog: '#5375FF',
    custom: '#43B573',
    snapshot: '#F1A82C',
}

function checkableMenuItem(
    label: string,
    count: number | null,
    icon: JSX.Element | null,
    isActive: boolean,
    onClick: () => void
): LemonMenuItem {
    return {
        label: (
            <div className="w-full flex flex-row justify-between items-center">
                <div className="flex flex-row items-center gap-1">
                    {isActive ? <IconCheck /> : <BaseIcon />}
                    {icon}
                    {label}
                </div>
                {count !== null && (
                    <span
                        // without setting fontVariant to none a single digit number between brackets gets rendered as a ligature
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ fontVariant: 'none' }}
                    >
                        ({count})
                    </span>
                )}
            </div>
        ),
        active: isActive,
        onClick: onClick,
    }
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

function EventRow({
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

function ToolbarIconButton({
    onClick,
    title,
    disabled,
    children,
}: {
    onClick: () => void
    title: string
    disabled?: boolean
    children: React.ReactNode
}): JSX.Element {
    return (
        <Tooltip title={title}>
            <button
                className={clsx(
                    'flex items-center justify-center shrink-0 w-6 h-6 rounded cursor-pointer',
                    disabled ? 'opacity-30 cursor-not-allowed' : 'hover:bg-surface-primary'
                )}
                onClick={disabled ? undefined : onClick}
            >
                {children}
            </button>
        </Tooltip>
    )
}

export const EventDebugMenu = (): JSX.Element => {
    const {
        searchText,
        isCollapsedEventRow,
        activeFilteredEvents,
        pinnedEvents,
        unpinnedEvents,
        pinnedEventIds,
        searchFilteredEventsCount,
        selectedEventTypes,
        hidePostHogProperties,
        hidePostHogFlags,
        expandedProperties,
        exportableEvents,
        totalEventsCount,
        isPaused,
        bufferedCount,
        relativeTimestamps,
    } = useValues(eventDebugMenuLogic)
    const {
        markExpanded,
        setSelectedEventType,
        setSearchText,
        setHidePostHogProperties,
        setHidePostHogFlags,
        togglePinnedEvent,
        toggleRelativeTimestamps,
        togglePaused,
        clearEvents,
    } = useActions(eventDebugMenuLogic)
    const { setVisibleMenu } = useActions(toolbarLogic)

    const handleExport = (): void => {
        const json = JSON.stringify(exportableEvents, null, 2)
        const blob = new Blob([json], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `posthog-events-${dayjs().format('YYYY-MM-DD-HHmmss')}.json`
        a.click()
        URL.revokeObjectURL(url)
    }

    const showEventsMenuItems = [
        checkableMenuItem(
            'PostHog events',
            searchFilteredEventsCount['posthog'],
            <IconLogomark />,
            selectedEventTypes.includes('posthog'),
            () => setSelectedEventType('posthog', !selectedEventTypes.includes('posthog'))
        ),
        checkableMenuItem(
            'Custom events',
            searchFilteredEventsCount['custom'],
            <IconVideoCamera />,
            selectedEventTypes.includes('custom'),
            () => setSelectedEventType('custom', !selectedEventTypes.includes('custom'))
        ),
        checkableMenuItem(
            'Replay events',
            searchFilteredEventsCount['snapshot'],
            <IconUnverifiedEvent />,
            selectedEventTypes.includes('snapshot'),
            () => setSelectedEventType('snapshot', !selectedEventTypes.includes('snapshot'))
        ),
    ]

    const hideThingsMenuItems = [
        checkableMenuItem('Hide PostHog properties', null, null, hidePostHogProperties, () =>
            setHidePostHogProperties(!hidePostHogProperties)
        ),
        checkableMenuItem('Hide PostHog flags', null, null, hidePostHogFlags, () =>
            setHidePostHogFlags(!hidePostHogFlags)
        ),
    ]

    const renderEventRow = (e: EventType): JSX.Element => {
        const expanded = e.uuid !== undefined && !isCollapsedEventRow(e.uuid)
        const isPinned = !!e.uuid && pinnedEventIds.has(e.uuid)

        return (
            <EventRow
                key={e.uuid}
                e={e}
                expanded={expanded}
                isPinned={isPinned}
                expandedProperties={expandedProperties}
                searchText={searchText}
                relativeTimestamps={relativeTimestamps}
                onToggleExpand={() => (expanded ? markExpanded(null) : markExpanded(e.uuid || null))}
                onTogglePin={togglePinnedEvent}
            />
        )
    }

    const isFiltered = activeFilteredEvents.length !== totalEventsCount
    const showingLabel = isFiltered
        ? `${activeFilteredEvents.length} of ${totalEventsCount}`
        : `${activeFilteredEvents.length}`

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex flex-row items-center gap-1 pb-1">
                    <LemonInput
                        autoFocus={true}
                        fullWidth={true}
                        placeholder="Filter events (or /regex/)"
                        type="search"
                        value={searchText}
                        onChange={setSearchText}
                    />
                    <Tooltip title={isPaused ? 'Paused' : 'Live'} className="ml-1">
                        <span
                            className={clsx(
                                'inline-block w-2 h-2 rounded-full shrink-0',
                                isPaused ? 'bg-muted opacity-50' : 'animate-pulse'
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={
                                isPaused
                                    ? undefined
                                    : { backgroundColor: '#43B573', boxShadow: '0 0 6px 2px rgba(67, 181, 115, 0.5)' }
                            }
                        />
                    </Tooltip>
                    <ToolbarIconButton
                        onClick={togglePaused}
                        title={isPaused ? `Resume (${bufferedCount} buffered)` : 'Pause stream'}
                    >
                        {isPaused ? <IconPlay className="text-secondary" /> : <IconPause className="text-secondary" />}
                    </ToolbarIconButton>
                    <ToolbarIconButton onClick={clearEvents} title="Clear events" disabled={totalEventsCount === 0}>
                        <IconTrash className="text-secondary" />
                    </ToolbarIconButton>
                    <ToolbarIconButton onClick={() => setVisibleMenu('none')} title="Close event debugger">
                        <IconX className="text-secondary" />
                    </ToolbarIconButton>
                </div>
                {isPaused && bufferedCount > 0 && (
                    <div className="text-xxs text-warning pb-1">
                        Paused — {bufferedCount} new event{bufferedCount !== 1 ? 's' : ''} buffered
                    </div>
                )}
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="flex flex-col gap-0.5">
                    {!activeFilteredEvents.length ? (
                        <div className="px-4 py-2 text-sm text-secondary">
                            {searchText
                                ? 'No events match your filters.'
                                : 'Interact with your page to see events here.'}
                        </div>
                    ) : (
                        <>
                            {pinnedEvents.length > 0 && (
                                <>
                                    <div className="text-xxs font-bold text-secondary uppercase tracking-wide pl-1">
                                        Pinned
                                    </div>
                                    {pinnedEvents.map(renderEventRow)}
                                    {unpinnedEvents.length > 0 && (
                                        <div className="text-xxs font-bold text-secondary uppercase tracking-wide pl-1 pt-1">
                                            Events
                                        </div>
                                    )}
                                </>
                            )}
                            {unpinnedEvents.map(renderEventRow)}
                        </>
                    )}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <SettingsBar border="none" className="justify-between">
                    <div className="flex flex-row items-center">
                        <SettingsMenu
                            items={hideThingsMenuItems}
                            highlightWhenActive={false}
                            icon={<IconHide />}
                            label="Hide"
                        />
                        <ToolbarIconButton
                            onClick={handleExport}
                            title="Export events as JSON"
                            disabled={activeFilteredEvents.length === 0}
                        >
                            <IconDownload className="text-secondary text-sm" />
                        </ToolbarIconButton>
                        <ToolbarIconButton
                            onClick={toggleRelativeTimestamps}
                            title={relativeTimestamps ? 'Show absolute timestamps' : 'Show relative timestamps'}
                        >
                            <IconClock
                                className={clsx('text-sm', relativeTimestamps ? 'text-primary' : 'text-secondary')}
                            />
                        </ToolbarIconButton>
                    </div>
                    <SettingsMenu
                        items={showEventsMenuItems}
                        highlightWhenActive={false}
                        icon={<IconEye />}
                        label={`Showing ${showingLabel}`}
                    />
                </SettingsBar>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
