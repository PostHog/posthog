import { useActions, useValues } from 'kea'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

import { eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'

import { ToolbarMenu } from '../bar/ToolbarMenu'

export const EventDebugMenu = (): JSX.Element => {
    const {
        searchType,
        searchText,
        filteredEvents,
        isCollapsedEventRow,
        expandedEvent,
        showRecordingSnapshots,
        snapshotCount,
        eventCount,
        filteredProperties,
    } = useValues(eventDebugMenuLogic)
    const { setSearchType, markExpanded, setShowRecordingSnapshots, setSearchText } = useActions(eventDebugMenuLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex flex-col pb-2 space-y-1">
                    <div className="flex flex-row justify-around items-center">
                        <span className="text-xs">Seen {eventCount} events.</span>
                        <LemonCheckbox
                            checked={showRecordingSnapshots}
                            onChange={(c) => setShowRecordingSnapshots(c)}
                            label={`Show ${snapshotCount} snapshot events`}
                            size="small"
                        />
                    </div>
                    <div className="flex justify-center flex-col">
                        <div className="flex flex-row items-center justify-between space-x-2">
                            <span>search:</span>
                            <LemonSegmentedButton
                                size="small"
                                value={searchType}
                                options={[
                                    {
                                        value: 'events',
                                        label: 'events',
                                    },
                                    { value: 'properties', label: 'properties' },
                                ]}
                                onChange={setSearchType}
                            />

                            <LemonInput fullWidth={true} type="search" value={searchText} onChange={setSearchText} />
                        </div>
                    </div>
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="flex flex-col space-y-1">
                    {filteredEvents.length ? (
                        filteredEvents.map((e) => {
                            return (
                                <div
                                    className="-mx-1 py-1 px-2 cursor-pointer"
                                    key={e.uuid}
                                    onClick={() => {
                                        expandedEvent === e.uuid ? markExpanded(null) : markExpanded(e.uuid || null)
                                    }}
                                >
                                    <div className="flex flex-row justify-between">
                                        <div>{e.event}</div>
                                        <div>
                                            <TZLabel time={e.timestamp} />
                                        </div>
                                    </div>
                                    <AnimatedCollapsible
                                        collapsed={e.uuid === undefined ? true : isCollapsedEventRow(e.uuid)}
                                    >
                                        <div className="my-1 ml-1 pl-2 border-l-2">
                                            <SimpleKeyValueList
                                                item={filteredProperties(e.properties)}
                                                emptyMessage={
                                                    searchText && searchType === 'properties'
                                                        ? 'No matching properties'
                                                        : 'No properties'
                                                }
                                            />
                                        </div>
                                    </AnimatedCollapsible>
                                </div>
                            )
                        })
                    ) : (
                        <div className="px-4 py-2">
                            {searchText && searchType === 'events'
                                ? 'No events match your search.'
                                : 'Interact with your page and then come back to the toolbar to see what events were generated.'}
                        </div>
                    )}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <span className="text-xs">View events from this page as they are sent to PostHog.</span>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
