import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSwitch } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { AUTOLOAD_INTERVAL, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

export function AutoLoad(): JSX.Element {
    const { autoLoadToggled, canLoadNewData } = useValues(dataNodeLogic)
    const { toggleAutoLoad, startAutoLoad, stopAutoLoad } = useActions(dataNodeLogic)

    useEffect(() => {
        startAutoLoad()
        return () => stopAutoLoad()
    }, [startAutoLoad, stopAutoLoad])

    const intervalSeconds = Math.round(AUTOLOAD_INTERVAL / 1000)

    return (
        <Tooltip
            title={
                canLoadNewData
                    ? `Automatically refresh new rows every ${intervalSeconds} seconds`
                    : 'Auto-refresh is unavailable for this query'
            }
        >
            <span>
                <LemonSwitch
                    bordered
                    size="small"
                    checked={autoLoadToggled && canLoadNewData}
                    disabled={!canLoadNewData}
                    onChange={toggleAutoLoad}
                    label="Auto-refresh"
                />
            </span>
        </Tooltip>
    )
}
