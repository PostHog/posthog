import { useActions, useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { useEffect } from 'react'

export function AutoLoad(): JSX.Element {
    const { autoLoadEnabled } = useValues(dataNodeLogic)
    const { startAutoLoad, stopAutoLoad, toggleAutoLoad } = useActions(dataNodeLogic)

    useEffect(() => {
        startAutoLoad()
        return () => stopAutoLoad()
    }, [])

    return (
        <LemonSwitch
            bordered
            data-attr="live-events-refresh-toggle"
            id="autoload-switch"
            label="Automatically load new events"
            checked={autoLoadEnabled}
            onChange={toggleAutoLoad}
        />
    )
}
