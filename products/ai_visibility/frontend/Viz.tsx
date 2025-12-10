import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { vizLogic } from './vizLogic'

const Viz: React.FC = () => {
    const { currentLocation } = useValues(router)
    const domain = useMemo(() => {
        const match = currentLocation.pathname?.match(/^\/viz\/(.+)/)
        return match?.[1] ? decodeURIComponent(match[1]) : ''
    }, [currentLocation.pathname])
    const logic = useMemo(() => vizLogic({ domain }), [domain])
    useMountedLogic(logic)
    const { loadTriggerResult } = useActions(logic)
    const { workflowId, workflowStatus, triggerResultLoading, lastError } = useValues(logic)

    return (
        <div className="flex flex-col gap-3 p-4 max-w-2xl mx-auto">
            <div>
                <h2 className="text-lg font-semibold">AI Visibility</h2>
                <p className="text-sm text-muted">
                    Starting workflow for domain: <span className="font-mono">{domain || 'unknown'}</span>
                </p>
            </div>

            <div className="rounded border border-border bg-bg-300 p-3">
                {triggerResultLoading ? (
                    <div className="flex items-center gap-2">
                        <Spinner />
                        <span>Triggering workflow…</span>
                    </div>
                ) : lastError ? (
                    <div className="flex flex-col gap-2">
                        <span className="text-danger font-semibold">Failed to start workflow</span>
                        <code className="text-xs break-all">{lastError}</code>
                        <LemonButton type="primary" onClick={() => loadTriggerResult()}>
                            Retry
                        </LemonButton>
                    </div>
                ) : (
                    <div className="flex flex-col gap-1">
                        <div className="flex gap-2">
                            <span className="text-muted">Workflow ID:</span>
                            <span className="font-mono">{workflowId ?? 'pending'}</span>
                        </div>
                        <div className="flex gap-2">
                            <span className="text-muted">Status:</span>
                            <span className="font-mono">{workflowStatus ?? 'pending'}</span>
                        </div>
                        <div className="flex gap-2">
                            <LemonButton
                                type="secondary"
                                onClick={() => loadTriggerResult()}
                                loading={triggerResultLoading}
                            >
                                Re-trigger
                            </LemonButton>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}

export default Viz
