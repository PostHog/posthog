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

export function PlayerFilter({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const logicProps = { sessionRecordingId, playerKey }
    const { windowIdFilter, showOnlyMatching, tab } = useValues(sharedListLogic(logicProps))
    const { setWindowIdFilter, setShowOnlyMatching } = useActions(sharedListLogic(logicProps))
    const { localFilters } = useValues(eventsListLogic(logicProps))
    const { setLocalFilters } = useActions(eventsListLogic(logicProps))
    const { windowIds } = useValues(metaLogic(logicProps))

    return (
        <>
            {tab === SessionRecordingTab.EVENTS && (
                <LemonInput
                    onChange={(query) => setLocalFilters({ query })}
                    placeholder="Search events"
                    type="search"
                    value={localFilters.query}
                />
            )}
            <LemonSelect
                className="player-filter-window"
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
            {tab === SessionRecordingTab.EVENTS && (
                <>
                    <LemonSwitch
                        className="player-filter-matching-events"
                        checked={showOnlyMatching}
                        bordered
                        label="Only show matching events"
                        onChange={setShowOnlyMatching}
                        size="small"
                    />
                    <Tooltip
                        title="Display only the events that match the global filter."
                        className="text-base text-muted-alt mr-2"
                    >
                        <IconInfo />
                    </Tooltip>
                </>
            )}
        </>
    )
}
