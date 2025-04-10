import { IconDatabaseBolt } from '@posthog/icons'
import clsx from 'clsx'
import { useValues } from 'kea'
import { Popover } from 'lib/lemon-ui/Popover'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useState } from 'react'
import { multitabEditorLogic } from 'scenes/data-warehouse/editor/multitabEditorLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryTiming } from '~/queries/schema/schema-general'

export interface TimingsProps {
    timings: QueryTiming[]
    elapsedTime?: number
}

export function Timings({ timings, elapsedTime }: TimingsProps): JSX.Element | null {
    return (
        <div className="deprecated-space-y-2 p-2">
            {timings.map(({ k: key, t: time }) => (
                <div
                    key={key}
                    className={clsx(
                        'flex justify-between items-start deprecated-space-x-2',
                        time > timings[timings.length - 1].t * 0.5 ? 'font-bold' : ''
                    )}
                >
                    <div>{key == '.' ? 'Query total' : key}</div>
                    <div>{time.toFixed(3)}s</div>
                </div>
            ))}
            {elapsedTime !== undefined && timings.length > 0 ? (
                <div className={clsx('flex justify-between items-start deprecated-space-x-2')}>
                    <div>+ HTTP overhead</div>
                    <div>{(elapsedTime / 1000 - timings[timings.length - 1].t).toFixed(3)}s</div>
                </div>
            ) : null}
        </div>
    )
}

function MaterializationSuggestion(): JSX.Element {
    return (
        <Tooltip title="Consider materializing this long running query for better performance">
            <IconDatabaseBolt className="text-warning text-xs cursor-help" />
        </Tooltip>
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
    const { elapsedTime, loadingStart, responseError, isShowingCachedResults, timings, query } =
        useValues(dataNodeLogic)
    const [, setTick] = useState(0)

    const { editingView } = useValues(multitabEditorLogic)
    const { dataWarehouseSavedQueryMapById } = useValues(dataWarehouseViewsLogic)
    const savedQuery = editingView ? dataWarehouseSavedQueryMapById[editingView.id] : null
    const isAlreadyMaterialized = !!savedQuery?.last_run_at

    if ('query' in query && query.query === '') {
        return null
    }

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

    const showMaterializationSuggestion = time >= 10000 // if query runs for longer than 10 seconds
    return (
        <div className="flex items-center gap-1">
            {showMaterializationSuggestion && !isAlreadyMaterialized && <MaterializationSuggestion />}
            <div className={responseError ? 'text-danger' : ''}>{(time / 1000).toFixed(time < 1000 ? 2 : 1)}s</div>
        </div>
    )
}
