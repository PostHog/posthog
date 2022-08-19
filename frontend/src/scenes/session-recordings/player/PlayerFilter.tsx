import React from 'react'
import { LemonSelect } from 'lib/components/LemonSelect'
import { useActions, useValues } from 'kea'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import { RecordingWindowFilter } from '~/types'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { sharedListLogic, WindowOption } from 'scenes/session-recordings/player/sharedListLogic'
import { IconInfo } from 'lib/components/icons'
import { Tooltip } from 'lib/components/Tooltip'

export function PlayerFilter(): JSX.Element {
    const { windowIdFilter } = useValues(sharedListLogic)
    const { setWindowIdFilter } = useActions(sharedListLogic)
    const { windowIds } = useValues(metaLogic)

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
        </>
    )
}
