import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { useState } from 'react'
import { Popover } from 'lib/lemon-ui/Popover'
import clsx from 'clsx'
import { QueryTiming } from '~/queries/schema'

function ElapsedTimeFinished({
    formattedTime,
    hasError,
    timings,
}: {
    formattedTime: string
    hasError: boolean
    timings: QueryTiming[]
}): JSX.Element | null {
    const [popoverVisible, setPopoverVisible] = useState(false)

    const overlay = (
        <div className="space-y-2 p-2">
            <div className="font-bold">Timings</div>
            {timings.map(({ k: key, t: time }) => (
                <div
                    key={key}
                    className={clsx(
                        'flex justify-between items-start space-x-2',
                        time > timings['.'] * 0.5 ? 'font-bold' : ''
                    )}
                >
                    <div>{key}</div>
                    <div>{time.toFixed(3)}s</div>
                </div>
            ))}
        </div>
    )
    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom"
            overlay={overlay}
        >
            <div
                onClick={() => setPopoverVisible((visible) => !visible)}
                className={clsx(hasError ? 'text-danger' : '', 'cursor-help')}
            >
                {formattedTime}
            </div>
        </Popover>
    )
}

export function ElapsedTime(): JSX.Element | null {
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

    const formattedTime = `${(time / 1000).toFixed(time < 1000 ? 2 : 1)}s`

    if (elapsedTime && timings) {
        return <ElapsedTimeFinished formattedTime={formattedTime} timings={timings} hasError={!!responseError} />
    }

    return <div className={responseError ? 'text-danger' : ''}>{formattedTime}</div>
}
