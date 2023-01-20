import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { useState } from 'react'

export function ElapsedTime(): JSX.Element | null {
    const { elapsedTime, loadingStart, responseError } = useValues(dataNodeLogic)
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

    return <div className={responseError ? 'text-danger' : ''}>{`${(time / 1000).toFixed(time < 1000 ? 2 : 1)}s`}</div>
}
