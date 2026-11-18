import { useActions, useValues } from 'kea'

import { IconClock, IconDownload, IconEye, IconHide, IconPause, IconPlay, IconTrash } from '@posthog/icons'

import { SettingsBar, SettingsMenu } from 'lib/components/PanelSettings/PanelSettings'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

import { eventTypeMenuItems, hidePropertiesMenuItems } from '~/toolbar/shared/debug/eventDebugMenuItems'
import { EventRow } from '~/toolbar/shared/debug/EventRow'
import { EventType } from '~/types'

import type { PageEventsCommand } from '../../logics/page/extensionPageEventsLogic'
import { extensionEventsLogic } from '../../logics/panel/extensionEventsLogic'
import { extensionPageToolbarConnectionLogic } from '../../logics/panel/extensionPageToolbarConnectionLogic'
import { DebugEventRow, PageToolbarEventsState } from '../../messaging/pageToolbarBridge'
import { ExtensionToolLoading } from '../panel/ExtensionToolLoading'
import { NoPagePosthogBanner } from '../panel/NoPagePosthogBanner'

function asEvent(row: DebugEventRow, eventsState: PageToolbarEventsState): EventType {
    const payload = row.uuid === eventsState.expandedEventId ? eventsState.expandedEventPayload : null
    return {
        uuid: row.uuid,
        event: row.event,
        timestamp: row.timestamp,
        properties: (payload?.properties as Record<string, any> | undefined) ?? {},
    } as EventType
}

export function ExtensionEventsMenu(): JSX.Element {
    const { eventsState, searchText } = useValues(extensionEventsLogic)
    const { setSearchText, exportEvents } = useActions(extensionEventsLogic)
    const { sendCommand } = useActions(extensionPageToolbarConnectionLogic)
    const send = (command: PageEventsCommand): void => sendCommand({ tool: 'events', command })

    if (!eventsState) {
        return <ExtensionToolLoading />
    }
    const { rows, totalCount, filteredCount, isPaused, bufferedCount } = eventsState
    const pinnedRows = rows.filter((row) => row.pinned)
    const unpinnedRows = rows.filter((row) => !row.pinned)
    const renderRow = (row: DebugEventRow): JSX.Element => (
        <EventRow
            key={row.uuid}
            e={asEvent(row, eventsState)}
            expanded={row.uuid === eventsState.expandedEventId}
            isPinned={row.pinned}
            expandedProperties={eventsState.expandedProperties}
            searchText={searchText}
            relativeTimestamps={eventsState.relativeTimestamps}
            onToggleExpand={() =>
                send({ type: 'expand-event', uuid: row.uuid === eventsState.expandedEventId ? null : row.uuid })
            }
            onTogglePin={(uuid) => send({ type: 'toggle-pinned-event', uuid })}
        />
    )

    return (
        <div className="flex flex-col gap-2">
            {!eventsState.available && <NoPagePosthogBanner consequence="the debugger can't see its events." />}
            <div className="flex items-center gap-1">
                <LemonInput
                    className="flex-1 min-w-0"
                    type="search"
                    size="small"
                    placeholder="Filter events (or /regex/)"
                    value={searchText}
                    onChange={setSearchText}
                    data-attr="toolbar-extension-events-search"
                />
                <LemonTag type={isPaused ? 'muted' : 'success'}>{isPaused ? 'Paused' : 'Live'}</LemonTag>
                <LemonButton
                    size="small"
                    icon={isPaused ? <IconPlay /> : <IconPause />}
                    tooltip={isPaused ? `Resume (${bufferedCount} buffered)` : 'Pause the stream'}
                    onClick={() => send({ type: 'toggle-events-paused' })}
                    data-attr="toolbar-extension-events-pause"
                />
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    tooltip="Clear events"
                    disabledReason={totalCount === 0 ? 'No events to clear' : null}
                    onClick={() => send({ type: 'clear-events' })}
                    data-attr="toolbar-extension-events-clear"
                />
            </div>
            {isPaused && bufferedCount > 0 && (
                <div className="text-xs text-warning">
                    Paused. {bufferedCount} new {bufferedCount === 1 ? 'event is' : 'events are'} waiting.
                </div>
            )}
            {rows.length === 0 ? (
                <div className="p-2 text-xs text-secondary">
                    {totalCount > 0 ? 'No events match your filters.' : 'Interact with your page to see events here.'}
                </div>
            ) : (
                <div className="flex flex-col gap-0.5" translate="no">
                    {pinnedRows.length > 0 && (
                        <>
                            <div className="text-xxs font-bold text-secondary uppercase tracking-wide pl-1">Pinned</div>
                            {pinnedRows.map(renderRow)}
                            {unpinnedRows.length > 0 && (
                                <div className="text-xxs font-bold text-secondary uppercase tracking-wide pl-1 pt-1">
                                    Events
                                </div>
                            )}
                        </>
                    )}
                    {unpinnedRows.map(renderRow)}
                </div>
            )}
            {rows.length < filteredCount && (
                <div className="text-xs text-secondary">
                    The panel shows the newest {rows.length} of {filteredCount} events. Export them to see all of them.
                </div>
            )}
            <SettingsBar border="top" className="justify-between flex-wrap">
                <div className="flex items-center">
                    <SettingsMenu
                        items={hidePropertiesMenuItems(
                            eventsState.hidePostHogProperties,
                            eventsState.hidePostHogFlags,
                            (hide) => send({ type: 'set-hide-posthog-properties', hide }),
                            (hide) => send({ type: 'set-hide-posthog-flags', hide })
                        )}
                        highlightWhenActive={false}
                        icon={<IconHide />}
                        label="Hide"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconDownload />}
                        tooltip="Export events as JSON"
                        disabledReason={filteredCount === 0 ? 'No events to export' : null}
                        onClick={exportEvents}
                        data-attr="toolbar-extension-events-export"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconClock />}
                        active={eventsState.relativeTimestamps}
                        tooltip={
                            eventsState.relativeTimestamps ? 'Show absolute timestamps' : 'Show relative timestamps'
                        }
                        onClick={() => send({ type: 'toggle-relative-timestamps' })}
                    />
                </div>
                <SettingsMenu
                    items={eventTypeMenuItems(
                        eventsState.countsByType,
                        eventsState.selectedEventTypes,
                        (eventType, enabled) => send({ type: 'set-event-type-enabled', eventType, enabled })
                    )}
                    highlightWhenActive={false}
                    icon={<IconEye />}
                    label={
                        filteredCount === totalCount
                            ? `Showing ${totalCount}`
                            : `Showing ${filteredCount} of ${totalCount}`
                    }
                />
            </SettingsBar>
        </div>
    )
}
