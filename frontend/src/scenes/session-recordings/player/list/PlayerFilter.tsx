import React from 'react'
import { LemonSelect } from 'lib/components/LemonSelect'
import { useActions, useValues } from 'kea'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import { RecordingWindowFilter, SessionRecordingPlayerProps, SessionRecordingTab } from '~/types'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { sharedListLogic, WindowOption } from 'scenes/session-recordings/player/list/sharedListLogic'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { eventsListLogic } from 'scenes/session-recordings/player/list/eventsListLogic'

export function PlayerFilter({ sessionRecordingId, playerKey, matching }: SessionRecordingPlayerProps): JSX.Element {
    const logicProps = { sessionRecordingId, playerKey }
    const { windowIdFilter, showOnlyMatching, tab } = useValues(sharedListLogic(logicProps))
    const { setWindowIdFilter, setShowOnlyMatching } = useActions(sharedListLogic(logicProps))
    const { localFilters } = useValues(eventsListLogic(logicProps))
    const { setLocalFilters } = useActions(eventsListLogic(logicProps))
    const { windowIds } = useValues(metaLogic(logicProps))

    return (
        <div className="flex justify-between gap-2 bg-side p-2 flex-wrap">
            <div className="flex items-center gap-2">
                {tab === SessionRecordingTab.EVENTS && (
                    <>
                        <LemonInput
                            onChange={(query) => setLocalFilters({ query })}
                            placeholder="Search events"
                            type="search"
                            value={localFilters.query}
                        />
                        {matching?.length ? (
                            <LemonSwitch
                                checked={showOnlyMatching}
                                bordered
                                label={
                                    <span className="flex items-center gap-2 whitespace-nowrap">
                                        Only show matching events
                                        <Tooltip
                                            title="Display only the events that match the global filter."
                                            className="text-base text-muted-alt mr-2"
                                        >
                                            <IconInfo />
                                        </Tooltip>
                                    </span>
                                }
                                onChange={setShowOnlyMatching}
                            />
                        ) : null}
                    </>
                )}
            </div>

            <div className="flex items-center gap-2">
                <LemonSelect
                    data-attr="player-window-select"
                    value={windowIdFilter ?? undefined}
                    onChange={(val) => setWindowIdFilter(val as WindowOption)}
                    options={[
                        {
                            value: RecordingWindowFilter.All,
                            label: 'All windows',
                            icon: <IconWindow value="A" className="text-muted" />,
                        },
                        ...windowIds.map((windowId, index) => ({
                            value: windowId,
                            label: `Window ${index + 1}`,
                            icon: <IconWindow value={index + 1} className="text-muted" />,
                        })),
                    ]}
                />
                <Tooltip
                    title="Each recording window translates to a distinct browser tab or window."
                    className="text-base text-muted-alt mr-2"
                >
                    <IconInfo />
                </Tooltip>
            </div>
        </div>
    )
}
