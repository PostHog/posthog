import { useActions, useValues } from 'kea'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { useEffect } from 'react'

import { AUTOLOAD_INTERVAL, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

export function AutoLoad(): JSX.Element {
    const { autoLoadToggled } = useValues(dataNodeLogic)
    const { startAutoLoad, stopAutoLoad, toggleAutoLoad } = useActions(dataNodeLogic)

    // Reload data only when this AutoLoad component is mounted.
    // This avoids needless reloading in the background, as logics might be kept
    // around, even if not visually present.
    useEffect(() => {
        startAutoLoad()
        return () => stopAutoLoad()
    }, [])

    return (
        <div className="flex items-center gap-2">
            <LemonSwitch
                bordered
                data-attr="live-events-refresh-toggle"
                id="autoload-switch"
                label="Automatically load new events"
                checked={autoLoadToggled}
                onChange={toggleAutoLoad}
                tooltip={`Load new events every ${AUTOLOAD_INTERVAL / 1000} seconds.`}
            />
        </div>
    )
}
