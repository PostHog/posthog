import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconClock, IconDownload, IconEye, IconHide, IconPause, IconPlay, IconTrash, IconX } from '@posthog/icons'

import { SettingsBar, SettingsMenu } from 'lib/components/PanelSettings/PanelSettings'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { toolbarLogic } from '~/toolbar/shared/bar/toolbarLogic'
import { downloadEventsAsJson } from '~/toolbar/shared/debug/downloadEventsAsJson'
import { eventTypeMenuItems, hidePropertiesMenuItems } from '~/toolbar/shared/debug/eventDebugMenuItems'
import { eventDebugMenuLogic } from '~/toolbar/shared/debug/eventDebugMenuLogic'
import { EventRow } from '~/toolbar/shared/debug/EventRow'
import { EventType } from '~/types'

import { ToolbarMenu } from '../bar/ToolbarMenu'

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

    const showEventsMenuItems = eventTypeMenuItems(searchFilteredEventsCount, selectedEventTypes, setSelectedEventType)
    const hideThingsMenuItems = hidePropertiesMenuItems(
        hidePostHogProperties,
        hidePostHogFlags,
        setHidePostHogProperties,
        setHidePostHogFlags
    )

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
                            onClick={() => downloadEventsAsJson(exportableEvents)}
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
