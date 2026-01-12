import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import { notebookLogic } from './notebookLogic'

const statusTone: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'default' }> = {
    running: { label: 'Running', tone: 'success' },
    starting: { label: 'Starting', tone: 'warning' },
    stopped: { label: 'Stopped', tone: 'default' },
    discarded: { label: 'Discarded', tone: 'default' },
    error: { label: 'Error', tone: 'danger' },
}

export const NotebookKernelInfo = (): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const logic = notebookKernelInfoLogic({ shortId })
    const { kernelInfo, kernelInfoLoading, executionResult, actionInFlight, isRunning } = useValues(logic)
    const { clearExecution, executeKernel, loadKernelInfo, restartKernel, startKernel, stopKernel } = useActions(logic)
    const [code, setCode] = useState('print("Kernel ready")')

    const statusInfo = useMemo(() => {
        if (!kernelInfo) {
            return null
        }
        return statusTone[kernelInfo.status] ?? { label: kernelInfo.status, tone: 'default' }
    }, [kernelInfo])

    return (
        <LemonWidget
            className="NotebookColumn__widget"
            title="Kernel info"
            actions={
                <LemonButton size="xsmall" type="secondary" onClick={() => loadKernelInfo()}>
                    Refresh
                </LemonButton>
            }
        >
            {kernelInfoLoading ? (
                <div className="flex items-center gap-2 text-muted text-sm p-3">
                    <Spinner textColored />
                    Loading kernel status
                </div>
            ) : kernelInfo ? (
                <div className="space-y-3 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                        {statusInfo ? <LemonTag type={statusInfo.tone}>{statusInfo.label}</LemonTag> : null}
                        <LemonTag type="default">{kernelInfo.backend === 'modal' ? 'Modal' : 'Local'}</LemonTag>
                        {kernelInfo.cpu_cores ? <LemonTag type="default">{kernelInfo.cpu_cores} cores</LemonTag> : null}
                        {kernelInfo.memory_gb ? (
                            <LemonTag type="default">{kernelInfo.memory_gb} GB RAM</LemonTag>
                        ) : null}
                        {kernelInfo.disk_size_gb ? (
                            <LemonTag type="default">{kernelInfo.disk_size_gb} GB disk</LemonTag>
                        ) : null}
                    </div>
                    <div className="text-xs text-muted space-y-1">
                        {kernelInfo.last_used_at ? <div>Last used: {kernelInfo.last_used_at}</div> : null}
                        {kernelInfo.kernel_id ? <div>Kernel ID: {kernelInfo.kernel_id}</div> : null}
                        {kernelInfo.kernel_pid ? <div>Kernel PID: {kernelInfo.kernel_pid}</div> : null}
                        {kernelInfo.sandbox_id ? <div>Sandbox: {kernelInfo.sandbox_id}</div> : null}
                        {kernelInfo.last_error ? (
                            <div className="text-danger">Error: {kernelInfo.last_error}</div>
                        ) : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => startKernel()}
                            disabled={actionInFlight || isRunning}
                        >
                            Start
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => stopKernel()}
                            disabled={actionInFlight || !isRunning}
                        >
                            Stop
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => restartKernel()}
                            disabled={actionInFlight}
                        >
                            Restart
                        </LemonButton>
                    </div>
                    <div className="space-y-2">
                        <div className="text-xs font-semibold text-muted uppercase tracking-wide">Execute code</div>
                        <LemonTextArea
                            value={code}
                            onChange={setCode}
                            placeholder="Enter Python code"
                            className="text-xs font-mono"
                            rows={4}
                        />
                        <div className="flex gap-2">
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() => executeKernel(code)}
                                disabledReason={!code.trim() ? 'Enter code to execute' : undefined}
                                disabled={actionInFlight}
                            >
                                Execute
                            </LemonButton>
                            {executionResult ? (
                                <LemonButton size="small" type="secondary" onClick={() => clearExecution()}>
                                    Clear output
                                </LemonButton>
                            ) : null}
                        </div>
                        {executionResult ? (
                            <div className="space-y-2 text-xs">
                                {executionResult.stdout ? (
                                    <pre className="bg-bg-light border border-border rounded p-2 whitespace-pre-wrap">
                                        {executionResult.stdout}
                                    </pre>
                                ) : null}
                                {executionResult.stderr ? (
                                    <pre className="bg-bg-light border border-border rounded p-2 text-danger whitespace-pre-wrap">
                                        {executionResult.stderr}
                                    </pre>
                                ) : null}
                                {executionResult.result ? (
                                    <pre className="bg-bg-light border border-border rounded p-2 whitespace-pre-wrap">
                                        {JSON.stringify(executionResult.result, null, 2)}
                                    </pre>
                                ) : null}
                                {executionResult.error_name ? (
                                    <div className="text-danger">Error: {executionResult.error_name}</div>
                                ) : null}
                                {executionResult.traceback?.length ? (
                                    <pre className="bg-bg-light border border-border rounded p-2 text-danger whitespace-pre-wrap">
                                        {executionResult.traceback.join('\n')}
                                    </pre>
                                ) : null}
                            </div>
                        ) : null}
                    </div>
                </div>
            ) : (
                <div className="text-sm text-muted">Kernel status is unavailable.</div>
            )}
        </LemonWidget>
    )
}
