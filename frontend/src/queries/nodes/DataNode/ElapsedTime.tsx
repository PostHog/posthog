import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { useState } from 'react'

export function ElapsedTime(): JSX.Element | null {
    const { elapsedTime, loadingStart } = useValues(dataNodeLogic)
    const [, setTick] = useState(0)

    let time = elapsedTime

    if (loadingStart && !elapsedTime) {
        time = performance.now() - loadingStart
        window.requestAnimationFrame(() => {
            setTick((tick) => tick + 1)
        })
    }

    if (!time) {
        return null
    }

    if (time < 1000) {
        return <div>{(Math.round(time / 10) / 100).toFixed(2)}s</div>
    }

    return <div>{time ? `${(Math.round(time / 100) / 10).toFixed(1)}s` : ''}</div>
}
