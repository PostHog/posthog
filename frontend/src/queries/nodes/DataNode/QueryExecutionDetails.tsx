import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChip } from '@posthog/icons'

import { Popover } from 'lib/lemon-ui/Popover'

import { humanFriendlyMilliseconds, humanizeBytes } from '~/lib/utils'

import { dataNodeLogic } from './dataNodeLogic'

interface QueryExecutionDetailsProps {
    dataNodeLogicKey?: string
}

export function QueryExecutionDetails({ dataNodeLogicKey }: QueryExecutionDetailsProps): JSX.Element | null {
    const logic = dataNodeLogicKey ? dataNodeLogic({ key: dataNodeLogicKey, query: {} as any }) : dataNodeLogic
    const { queryLog, queryId, queryLogLoading, queryLogQueryId } = useValues(logic)
    const { loadQueryLog } = useActions(logic)

    const [popoverVisible, setPopoverVisible] = useState(false)

    if (!queryId) {
        return null
    }

    const executionDetails = queryLog?.results?.[0]
    const columns = queryLog?.columns || []

    let memoryUsage = null
    let cpuMicroseconds = null
    let readBytes = null
    let queryDurationMs = null

    if (executionDetails && columns.length > 0) {
        const memoryUsageIndex = columns.indexOf('memory_usage')
        const cpuMicrosecondsIndex = columns.indexOf('cpu_microseconds')
        const readBytesIndex = columns.indexOf('read_bytes')
        const queryDurationMsIndex = columns.indexOf('query_duration_ms')

        memoryUsage = memoryUsageIndex >= 0 ? executionDetails[memoryUsageIndex] : null
        cpuMicroseconds = cpuMicrosecondsIndex >= 0 ? executionDetails[cpuMicrosecondsIndex] : null
        readBytes = readBytesIndex >= 0 ? executionDetails[readBytesIndex] : null
        queryDurationMs = queryDurationMsIndex >= 0 ? executionDetails[queryDurationMsIndex] : null
    }

    const formatCpuTime = (microseconds: number): string => {
        if (microseconds < 1000) {
            return `${microseconds}μs`
        } else if (microseconds < 1000000) {
            return `${(microseconds / 1000).toFixed(2)}ms`
        }
        return `${(microseconds / 1000000).toFixed(2)}s`
    }

    const hasData = memoryUsage !== null || cpuMicroseconds !== null || readBytes !== null || queryDurationMs !== null

    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom"
            overlay={
                <div className="deprecated-space-y-1 p-2">
                    {queryLogLoading ? (
                        <div className="py-1">Loading execution details...</div>
                    ) : hasData ? (
                        <>
                            {memoryUsage !== null && (
                                <div className="flex justify-between items-start deprecated-space-x-2 py-1">
                                    <span>Memory usage:</span>
                                    <span className="font-mono">{humanizeBytes(memoryUsage)}</span>
                                </div>
                            )}
                            {readBytes !== null && (
                                <div className="flex justify-between items-start deprecated-space-x-2 py-1">
                                    <span>Data read:</span>
                                    <span className="font-mono">{humanizeBytes(readBytes)}</span>
                                </div>
                            )}
                            {cpuMicroseconds !== null && (
                                <div className="flex justify-between items-start deprecated-space-x-2 py-1">
                                    <span>CPU time:</span>
                                    <span className="font-mono">{formatCpuTime(cpuMicroseconds)}</span>
                                </div>
                            )}
                            {queryDurationMs !== null && (
                                <div className="flex justify-between items-start deprecated-space-x-2 py-1">
                                    <span>Duration:</span>
                                    <span className="font-mono">{humanFriendlyMilliseconds(queryDurationMs)}</span>
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="py-1">No execution details available.</div>
                    )}
                </div>
            }
        >
            <div
                onClick={() => {
                    const newVisible = !popoverVisible
                    setPopoverVisible(newVisible)
                    if (newVisible) {
                        posthog.capture('query execution details viewed')
                    }
                }}
                onMouseEnter={() => {
                    if (!queryLogLoading && queryId && queryId !== queryLogQueryId) {
                        loadQueryLog(queryId)
                    }
                    if (!popoverVisible) {
                        setPopoverVisible(true)
                        posthog.capture('query execution details viewed')
                    }
                }}
                onMouseLeave={() => setPopoverVisible(false)}
                className="cursor-help text-xs flex items-center gap-1"
            >
                <IconChip />
                Execution details
            </div>
        </Popover>
    )
}
