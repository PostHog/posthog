import { IconSearch } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { SettingsBar, SettingsToggle } from 'scenes/session-recordings/components/PanelSettings'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

import { eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'

import { ToolbarMenu } from '../bar/ToolbarMenu'

export const EventDebugMenu = (): JSX.Element => {
    const {
        searchText,
        filteredEvents,
        isCollapsedEventRow,
        expandedEvent,
        hideRecordingSnapshots,
        snapshotCount,
        eventCount,
        filteredProperties,
        searchVisible,
    } = useValues(eventDebugMenuLogic)
    const { markExpanded, setHideRecordingSnapshots, setSearchText, setSearchVisible } = useActions(eventDebugMenuLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex flex-col pb-2 space-y-1">
                    <div className="flex justify-center flex-col">
                        <SettingsBar border="none" className="justify-end">
                            <div className="flex-1 text-sm">
                                View events from this page as they are sent to PostHog.
                            </div>
                            <SettingsToggle
                                label="Search"
                                icon={<IconSearch />}
                                active={searchVisible}
                                onClick={() => setSearchVisible(!searchVisible)}
                            />
                        </SettingsBar>
                        {searchVisible && (
                            <div className="flex flex-row items-center justify-between space-x-2">
                                <LemonInput
                                    size="xsmall"
                                    fullWidth={true}
                                    type="search"
                                    value={searchText}
                                    onChange={setSearchText}
                                />
                            </div>
                        )}
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
                            {searchText && eventCount
                                ? 'Nothing matches your search.'
                                : 'Interact with your page and then come back to the toolbar to see what events were generated.'}
                        </div>
                    )}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer noPadding>
                <SettingsBar border="top" className="justify-around">
                    <span>Seen {eventCount} events.</span>
                    <SettingsToggle
                        title="Snapshot events can be used to debug session replay issues."
                        label={`${hideRecordingSnapshots ? 'Show' : 'Hide'} ${snapshotCount} snapshot events`}
                        active={hideRecordingSnapshots}
                        onClick={() => setHideRecordingSnapshots(!hideRecordingSnapshots)}
                    />
                </SettingsBar>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
