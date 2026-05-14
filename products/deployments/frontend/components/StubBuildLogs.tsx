import { useEffect, useState } from 'react'

import { LemonCard, LemonTag } from '@posthog/lemon-ui'

import type { DeploymentApi, DeploymentProjectApi } from '../generated/api.schemas'
import { getStubBuildLogs, POSTHOG_COM_BUILD_LOGS_URL, POSTHOG_COM_PROJECT_ID, StubBuildLogLine } from '../stubData'

interface JsonlLogLine {
    timestamp: string
    stream: 'stdout' | 'stderr'
    line: string
}

interface RenderedLogLine {
    time: string
    stream: 'stdout' | 'stderr' | StubBuildLogLine['level']
    line: string
}

const STREAM_TAG_TYPE: Record<RenderedLogLine['stream'], 'default' | 'success' | 'warning' | 'danger'> = {
    stdout: 'default',
    stderr: 'warning',
    info: 'default',
    success: 'success',
    warning: 'warning',
    error: 'danger',
}

function formatElapsed(timestamp: string, firstTimestamp: string): string {
    const elapsedSeconds = Math.max(
        0,
        Math.floor((new Date(timestamp).getTime() - new Date(firstTimestamp).getTime()) / 1000)
    )
    const minutes = Math.floor(elapsedSeconds / 60)
    const seconds = elapsedSeconds % 60
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

function parseJsonlLogs(contents: string): RenderedLogLine[] {
    const rows = contents
        .split('\n')
        .filter(Boolean)
        .map((line): JsonlLogLine | null => {
            try {
                return JSON.parse(line) as JsonlLogLine
            } catch {
                return null
            }
        })
        .filter((line): line is JsonlLogLine => !!line)

    const firstTimestamp = rows[0]?.timestamp
    if (!firstTimestamp) {
        return []
    }

    return rows.map((row) => ({
        time: formatElapsed(row.timestamp, firstTimestamp),
        stream: row.stream,
        line: row.line || ' ',
    }))
}

export function StubBuildLogs({
    deployment,
    project,
}: {
    deployment: DeploymentApi
    project: DeploymentProjectApi | null
}): JSX.Element {
    const [realLogs, setRealLogs] = useState<RenderedLogLine[] | null>(null)

    useEffect(() => {
        let cancelled = false
        if (deployment.deployment_project_id !== POSTHOG_COM_PROJECT_ID) {
            setRealLogs(null)
            return
        }

        fetch(POSTHOG_COM_BUILD_LOGS_URL)
            .then((response) => (response.ok ? response.text() : Promise.reject(new Error('Failed to load logs'))))
            .then((contents) => {
                if (!cancelled) {
                    setRealLogs(parseJsonlLogs(contents))
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setRealLogs(null)
                }
            })

        return () => {
            cancelled = true
        }
    }, [deployment.deployment_project_id])

    const fallbackLines: RenderedLogLine[] = getStubBuildLogs(deployment, project).map((line) => ({
        time: line.time,
        stream: line.level,
        line: line.message,
    }))
    const lines = realLogs ?? fallbackLines

    return (
        <LemonCard hoverEffect={false} className="overflow-hidden p-0">
            <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border bg-surface-secondary">
                <div className="flex flex-col">
                    <span className="font-semibold">Build logs</span>
                    <span className="text-xs text-secondary">{deployment.temporal_workflow_id || deployment.id}</span>
                </div>
                <LemonTag
                    type={
                        deployment.status === 'ready' ? 'success' : deployment.status === 'error' ? 'danger' : 'primary'
                    }
                >
                    {deployment.status === 'ready'
                        ? 'Complete'
                        : deployment.status === 'error'
                          ? 'Failed'
                          : 'Streaming'}
                </LemonTag>
            </div>
            <div className="bg-black text-white font-mono text-xs p-4 overflow-auto max-h-[32rem]">
                {lines.map((line, index) => (
                    <div key={`${line.time}-${index}`} className="grid grid-cols-[3.5rem_5rem_1fr] gap-3 py-1">
                        <span className="text-gray-400">{line.time}</span>
                        <span>
                            <LemonTag type={STREAM_TAG_TYPE[line.stream]}>{line.stream}</LemonTag>
                        </span>
                        <span
                            className={line.stream === 'stderr' || line.stream === 'error' ? 'text-red-300' : undefined}
                        >
                            {line.line}
                        </span>
                    </div>
                ))}
            </div>
        </LemonCard>
    )
}
