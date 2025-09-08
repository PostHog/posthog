import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { IconChip } from '@posthog/icons'

import { Popover } from 'lib/lemon-ui/Popover'

import { humanizeBytes } from '~/lib/utils'

import { dataNodeLogic } from './dataNodeLogic'

export function QueryExecutionDetail(): JSX.Element | null {
    const { queryLog } = useValues(dataNodeLogic)
    const [popoverVisible, setPopoverVisible] = useState(false)

    if (!queryLog?.results?.[0]) {
        return null
    }

    const executionDetails = queryLog.results[0]
    const columns = queryLog.columns || []

    const memoryUsageIndex = columns.indexOf('memory_usage')
    const cpuMicrosecondsIndex = columns.indexOf('cpu_microseconds')
    const readBytesIndex = columns.indexOf('read_bytes')

    const memoryUsage = memoryUsageIndex >= 0 ? executionDetails[memoryUsageIndex] : null
    const cpuMicroseconds = cpuMicrosecondsIndex >= 0 ? executionDetails[cpuMicrosecondsIndex] : null
    const readBytes = readBytesIndex >= 0 ? executionDetails[readBytesIndex] : null

    if (memoryUsage === null && cpuMicroseconds === null && readBytes === null) {
        return null
    }

    const formatCpuTime = (microseconds: number): string => {
        if (microseconds < 1000) {
            return `${microseconds}μs`
        } else if (microseconds < 1000000) {
            return `${(microseconds / 1000).toFixed(1)}ms`
        }
        return `${(microseconds / 1000000).toFixed(2)}s`
    }

    return (
        <Popover
            onClickOutside={() => setPopoverVisible(false)}
            visible={popoverVisible}
            placement="bottom"
            overlay={
                <div className="deprecated-space-y-1 p-2">
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
