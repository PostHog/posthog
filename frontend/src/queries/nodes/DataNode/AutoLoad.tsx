import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { useEffect } from 'react'
import { Spinner } from 'lib/components/Spinner/Spinner'

export function AutoLoad(): JSX.Element {
    const { autoLoadEnabled, newDataLoading } = useValues(dataNodeLogic)
    const { startAutoLoad, stopAutoLoad, toggleAutoLoad } = useActions(dataNodeLogic)

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
                checked={autoLoadEnabled}
                onChange={toggleAutoLoad}
            />
            {newDataLoading ? <Spinner className="text-2xl" /> : null}
        </div>
    )
}
