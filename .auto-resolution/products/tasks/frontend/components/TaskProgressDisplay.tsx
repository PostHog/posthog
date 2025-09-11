import { useCallback, useEffect, useState } from 'react'

import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { IconRefresh } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { ProgressResponse, ProgressStatus, Task } from '../types'

interface TaskProgressDisplayProps {
    task: Task
    className?: string
}

export function TaskProgressDisplay({ task, className = '' }: TaskProgressDisplayProps): JSX.Element {
    const [progress, setProgress] = useState<ProgressResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [autoRefresh, setAutoRefresh] = useState(true)

    const fetchProgress = useCallback(async (): Promise<void> => {
        try {
            setError(null)
            const response = await api.get(`api/projects/@current/tasks/${task.id}/progress/`)
            setProgress(response)

            // Auto-refresh if still in progress
            if (
                response.has_progress &&
                response.status &&
                [ProgressStatus.STARTED, ProgressStatus.IN_PROGRESS].includes(response.status)
            ) {
                setAutoRefresh(true)
            } else {
                setAutoRefresh(false)
            }
        } catch (err) {
            console.error('Progress fetch error:', err)
            const errorMessage = err instanceof Error ? err.message : 'Failed to fetch progress'
            setError(`API Error: ${errorMessage}`)
            setAutoRefresh(false)
        } finally {
            setLoading(false)
        }
    }, [task])

    useEffect(() => {
        fetchProgress()
    }, [task.id, fetchProgress])

    useEffect(() => {
        if (!autoRefresh) {
            return
        }

        const interval = setInterval(fetchProgress, 3000) // Refresh every 3 seconds
        return () => clearInterval(interval)
    }, [autoRefresh, fetchProgress])

    const formatOutputLog = (log: string): string[] => {
        return log.split('\n').filter((line) => line.trim())
    }

    const getStatusColor = (status: ProgressStatus | undefined): string => {
        switch (status) {
            case ProgressStatus.STARTED:
            case ProgressStatus.IN_PROGRESS:
                return 'text-primary'
            case ProgressStatus.COMPLETED:
                return 'text-success'
            case ProgressStatus.FAILED:
                return 'text-danger'
            default:
                return 'text-muted'
        }
    }

    const getStatusIcon = (status: ProgressStatus): string => {
        switch (status) {
            case ProgressStatus.STARTED:
            case ProgressStatus.IN_PROGRESS:
                return '⚡'
            case ProgressStatus.COMPLETED:
                return '✅'
            case ProgressStatus.FAILED:
                return '❌'
            default:
                return '⏸'
        }
    }

    if (loading) {
        return (
            <div className={`${className} flex items-center gap-2 p-3 bg-bg-light rounded border`}>
                <Spinner className="w-4 h-4" />
                <span className="text-sm text-muted">Loading execution progress...</span>
            </div>
        )
    }

    if (error) {
        return (
            <div className={`${className} p-3 bg-bg-light rounded border`}>
                <div className="flex items-center justify-between">
                    <span className="text-sm text-danger">Error: {error}</span>
                    <LemonButton icon={<IconRefresh />} size="xsmall" onClick={fetchProgress}>
                        Retry
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (!progress?.has_progress) {
        return (
            <div className={`${className} p-3 bg-bg-light rounded border`}>
                <span className="text-sm text-muted">No Claude Code execution found for this task</span>
            </div>
        )
    }

    return (
        <div className={`${className} space-y-3`}>
            {/* GitHub Integration */}
            {(task.github_branch || task.github_pr_url) && (
                <div className="p-3 bg-bg-light rounded border">
                    <h4 className="text-sm font-medium mb-2">GitHub Integration</h4>
                    <div className="space-y-2">
                        {task.github_branch && (
                            <div className="flex items-center gap-2 text-sm">
                                <span className="text-muted">Branch:</span>
                                <code className="px-2 py-1 bg-bg-dark rounded text-xs">{task.github_branch}</code>
                            </div>
                        )}
                        {task.github_pr_url && (
                            <div className="flex items-center gap-2 text-sm">
                                <span className="text-muted">Pull Request:</span>
                                <LemonButton
                                    icon={<IconExternal />}
                                    size="xsmall"
                                    type="primary"
                                    to={task.github_pr_url}
                                    targetBlank
                                >
                                    View PR
                                </LemonButton>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {/* Progress Display */}
            <div className="p-3 bg-bg-light rounded border">
                <div className="flex items-center justify-between mb-3">
                    <h4 className="text-sm font-medium">Claude Code Execution</h4>
                    <div className="flex items-center gap-2">
                        <span className={cn('text-sm', getStatusColor(progress.status))}>
                            {getStatusIcon(progress.status!)} {progress.status}
                        </span>
                        {autoRefresh && <Spinner className="w-3 h-3" />}
                    </div>
                </div>

                {/* Progress Bar - only show if we have meaningful progress tracking */}
                {progress.total_steps && progress.total_steps > 0 && (
                    <div className="mb-3">
                        <div className="flex justify-between text-xs text-muted mb-1">
                            <span>Progress</span>
                            <span>
                                {progress.completed_steps}/{progress.total_steps} steps
                            </span>
                        </div>
                        {progress.progress_percentage && (
                            <LemonProgress
                                percent={progress.progress_percentage}
                                strokeColor={progress.status === ProgressStatus.FAILED ? 'var(--danger)' : undefined}
                            />
                        )}
                    </div>
                )}

                {/* Current Step */}
                {progress.current_step && (
                    <div className="mb-3">
                        <span className="text-xs text-muted">Current step:</span>
                        <div className="text-sm font-medium">{progress.current_step}</div>
                    </div>
                )}

                {/* Error Message */}
                {progress.error_message && (
                    <div className="mb-3 p-2 bg-danger-highlight rounded">
                        <span className="text-xs text-danger font-medium">Error:</span>
                        <div className="text-sm text-danger">{progress.error_message}</div>
                    </div>
                )}

                {/* Output Log */}
                {progress.output_log && (
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-muted">Live Output:</span>
                            <LemonButton icon={<IconRefresh />} size="xsmall" onClick={fetchProgress} loading={loading}>
                                Refresh
                            </LemonButton>
                        </div>
                        <div className="bg-bg-dark rounded p-3 max-h-64 overflow-y-auto">
                            <pre className="text-xs text-default font-mono whitespace-pre-wrap">
                                {formatOutputLog(progress.output_log).map((line, idx) => (
                                    <div key={idx} className="mb-1">
                                        {line}
                                    </div>
                                ))}
                            </pre>
                        </div>
                    </div>
                )}

                {/* Timestamp Info */}
                <div className="mt-3 pt-3 border-t border-border">
                    <div className="flex justify-between text-xs text-muted">
                        <span>
                            Started: {progress.created_at ? new Date(progress.created_at).toLocaleString() : 'Unknown'}
                        </span>
                        {progress.completed_at && (
                            <span>Completed: {new Date(progress.completed_at).toLocaleString()}</span>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
