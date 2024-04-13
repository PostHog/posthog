import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { SimpleKeyValueList } from 'scenes/session-recordings/player/inspector/components/SimpleKeyValueList'

import { eventDebugMenuLogic } from '~/toolbar/debug/eventDebugMenuLogic'

import { ToolbarMenu } from '../bar/ToolbarMenu'

export const EventDebugMenu = (): JSX.Element => {
    const { events, isCollapsedEventRow, expandedEvent, showRecordingSnapshots } = useValues(eventDebugMenuLogic)
    const { markExpanded, setShowRecordingSnapshots } = useActions(eventDebugMenuLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex flex-col pb-2 space-y-1">
                    <div className="flex flex-row justify-around">
                        <span className="text-xs">
                            Seen {events.filter((e) => e.event !== '$snapshot').length} events.
                        </span>
                        <span className="text-xs">
                            Seen {events.filter((e) => e.event === '$snapshot').length} recording snapshots.
                        </span>
                    </div>
                    <div className="flex justify-center">
                        <LemonSwitch
                            checked={showRecordingSnapshots}
                            onChange={(c) => setShowRecordingSnapshots(c)}
                            label="Show recording snapshot events"
                        />
                    </div>
                </div>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="flex flex-col space-y-1 LiveCapture">
                    {events
                        .filter((e) => {
                            if (showRecordingSnapshots) {
                                return true
                            } else {
                                return e.event !== '$snapshot'
                            }
                        })
                        .map((e, i) => {
                            return (
                                <div
                                    className={clsx('-mx-1 py-1 px-2 cursor-pointer', i === 0 && 'bg-mark')}
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
                                        <SimpleKeyValueList
                                            item={e.event === '$snapshot' ? e : e.properties}
                                            emptyMessage="No events seen yet."
                                        />
                                    </AnimatedCollapsible>
                                </div>
                            )
                        })}
                </div>
            </ToolbarMenu.Body>
            <ToolbarMenu.Footer>
                <span className="text-xs">View events from this page as they are sent to PostHog.</span>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
