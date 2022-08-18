import React from 'react'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { LemonSelect } from 'lib/components/LemonSelect'
import { useActions, useValues } from 'kea'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import { RecordingWindowFilter } from '~/types'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { sharedListLogic, WindowOption } from 'scenes/session-recordings/player/sharedListLogic'
import { IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function PlayerFilter(): JSX.Element {
    const { windowIdFilter, onlyMatchingEvents } = useValues(sharedListLogic)
    const { setWindowIdFilter, setOnlyMatchingEvents } = useActions(sharedListLogic)
    const { windowIds } = useValues(metaLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const showFilters = !!featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYER_V3_FILTERING]

    return (
        <>
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
                className="text-base text-muted-alt"
            >
                <IconInfo />
            </Tooltip>
            {showFilters && (
                <LemonSwitch
                    className="player-filter-matching-events"
                    data-attr="player-matching-events"
                    label="Only show matching events"
                    checked={onlyMatchingEvents}
                    bordered
                    onChange={setOnlyMatchingEvents}
                />
            )}
        </>
    )
}
