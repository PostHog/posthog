import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import { useMemo } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Results } from './Results'
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
    const { workflowId, triggerResultLoading, lastError, isReady, results, runId, isPolling, triggerResult } =
        useValues(logic)

    // Only show loading spinner on initial load, not during polling
    const isInitialLoading = triggerResultLoading && !triggerResult

    return (
        <div className="flex flex-col gap-3 p-4 max-w-2xl mx-auto">
            <div>
                <h2 className="text-lg font-semibold">AI Visibility</h2>
                <p className="text-sm text-muted">
                    Domain: <span className="font-mono">{domain || 'unknown'}</span>
                </p>
            </div>

            {lastError ? (
                <div className="rounded border border-border bg-bg-300 p-3">
                    <div className="flex flex-col gap-2">
                        <span className="text-danger font-semibold">Failed to load results</span>
                        <code className="text-xs break-all">{lastError}</code>
                        <LemonButton type="primary" onClick={() => loadTriggerResult()}>
                            Retry
                        </LemonButton>
                    </div>
                </div>
            ) : isReady && results ? (
                <Results results={results} domain={domain} runId={runId} />
            ) : isInitialLoading ? (
                <div className="rounded border border-border bg-bg-300 p-3">
                    <div className="flex items-center gap-2">
                        <Spinner />
                        <span>Starting workflow...</span>
                    </div>
                </div>
            ) : isPolling ? (
                <div className="rounded border border-border bg-bg-300 p-3">
                    <div className="flex items-center gap-2">
                        <Spinner />
                        <span>Processing... checking again in 5 seconds</span>
                    </div>
                    {workflowId && (
                        <div className="mt-2 text-xs text-muted">
                            Workflow ID: <span className="font-mono">{workflowId}</span>
                        </div>
                    )}
                </div>
            ) : null}
        </div>
    )
}

export default Viz
