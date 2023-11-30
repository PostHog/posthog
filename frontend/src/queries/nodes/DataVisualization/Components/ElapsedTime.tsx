import { useMountedLogic, useValues } from 'kea'
import { useState } from 'react'

import { dataVisualizationLogic } from '../dataVisualizationLogic'

export const ElapsedTime = (): JSX.Element | null => {
    const logic = useMountedLogic(dataVisualizationLogic)

    const { elapsedTime, loadingStart, responseError, isShowingCachedResults } = useValues(logic)
    const [, setTick] = useState(0)

    let time = elapsedTime
    if (isShowingCachedResults) {
        time = 0
    }

    if (!isShowingCachedResults && loadingStart && !elapsedTime) {
        time = performance.now() - loadingStart
        window.requestAnimationFrame(() => {
            setTick((tick) => tick + 1)
        })
    }

    if (!time) {
        return null
    }

    return <div className={responseError ? 'text-danger' : ''}>{(time / 1000).toFixed(time < 1000 ? 2 : 1)}s</div>
}
