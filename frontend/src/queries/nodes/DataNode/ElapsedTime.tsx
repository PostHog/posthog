import clsx from 'clsx'
import { useValues } from 'kea'
import { Popover } from 'lib/lemon-ui/Popover'
import { useState } from 'react'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryTiming } from '~/queries/schema'

export interface TimingsProps {
    timings: QueryTiming[]
    elapsedTime: number
}

export function Timings({ timings, elapsedTime }: TimingsProps): JSX.Element | null {
    return (
        <div className="space-y-2 p-2">
            {timings.map(({ k: key, t: time }) => (
                <div
                    key={key}
                    className={clsx(
                        'flex justify-between items-start space-x-2',
                        time > timings[timings.length - 1].t * 0.5 ? 'font-bold' : ''
                    )}
                >
                    <div>{key == '.' ? 'Query total' : key}</div>
                    <div>{time.toFixed(3)}s</div>
                </div>
            ))}
            {timings.length > 0 ? (
                <div className={clsx('flex justify-between items-start space-x-2')}>
                    <div>+ HTTP overhead</div>
                    <div>{(elapsedTime / 1000 - timings[timings.length - 1].t).toFixed(3)}s</div>
                </div>
            ) : null}
        </div>
    )
}

function ElapsedTimeWithTimings({
    elapsedTime,
    hasError,
    timings,
}: {
    elapsedTime: number
    hasError: boolean
    timings: QueryTiming[]
}): JSX.Element | null {
    const [popoverVisible, setPopoverVisible] = useState(false)
    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom"
            overlay={<Timings timings={timings} elapsedTime={elapsedTime} />}
        >
            <div
                onClick={() => setPopoverVisible((visible) => !visible)}
                className={clsx(hasError ? 'text-danger' : '', 'cursor-help')}
            >
                {(elapsedTime / 1000).toFixed(elapsedTime < 1000 ? 2 : 1)}s
            </div>
        </Popover>
    )
}

export function ElapsedTime({ showTimings }: { showTimings?: boolean }): JSX.Element | null {
    const { elapsedTime, loadingStart, responseError, isShowingCachedResults, timings } = useValues(dataNodeLogic)
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

    if (elapsedTime && timings && showTimings) {
        return <ElapsedTimeWithTimings elapsedTime={elapsedTime} timings={timings} hasError={!!responseError} />
    }

    return <div className={responseError ? 'text-danger' : ''}>{(time / 1000).toFixed(time < 1000 ? 2 : 1)}s</div>
}
