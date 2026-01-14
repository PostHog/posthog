import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
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

const cpuCoreOptions = [0.125, 0.25, 0.5, 1, 2, 4, 6, 8, 16, 32, 64]
const memoryGbOptions = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256]
const idleTimeoutOptions = [
    { label: '10 minutes', value: 600 },
    { label: '30 minutes', value: 1800 },
    { label: '1 hour', value: 3600 },
    { label: '3 hours', value: 10800 },
    { label: '6 hours', value: 21600 },
    { label: '12 hours', value: 43200 },
]

const findClosestOptionIndex = (options: number[], value?: number | null): number => {
    if (value == null || Number.isNaN(value)) {
        return 0
    }
    const matchIndex = options.findIndex((option) => Math.abs(option - value) < 1e-6)
    if (matchIndex !== -1) {
        return matchIndex
    }
    return options.reduce((closestIndex, option, index) => {
        const closestValue = options[closestIndex]
        return Math.abs(option - value) < Math.abs(closestValue - value) ? index : closestIndex
    }, 0)
}

const formatCores = (value: number): string => {
    const formatted = value % 1 === 0 ? value.toString() : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
    return `${formatted} ${value === 1 ? 'core' : 'cores'}`
}

const formatMemory = (value: number): string => {
    if (value < 1) {
        return `${Math.round(value * 1024)} MB`
    }
    return `${value} GB`
}

export const NotebookKernelInfo = (): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const logic = notebookKernelInfoLogic({ shortId })
    const { kernelInfo, kernelInfoLoading, executionResult, actionInFlight, isRunning } = useValues(logic)
    const { clearExecution, executeKernel, loadKernelInfo, restartKernel, saveKernelConfig, startKernel, stopKernel } =
        useActions(logic)
    const [code, setCode] = useState('print("Kernel ready")')
    const [cpuIndex, setCpuIndex] = useState(0)
    const [memoryIndex, setMemoryIndex] = useState(0)
    const [idleTimeoutSeconds, setIdleTimeoutSeconds] = useState(idleTimeoutOptions[1].value)

    const statusInfo = useMemo(() => {
        if (!kernelInfo) {
            return null
        }
        if (actionInFlight.stop) {
            return { label: 'Stopping', tone: 'warning' }
        }
        if (actionInFlight.restart) {
            return { label: 'Restarting', tone: 'warning' }
        }
        if (actionInFlight.start && kernelInfo.status !== 'starting') {
            return { label: 'Starting', tone: 'warning' }
        }
        return statusTone[kernelInfo.status] ?? { label: kernelInfo.status, tone: 'default' }
    }, [actionInFlight.restart, actionInFlight.start, actionInFlight.stop, kernelInfo])

    const isStarting = kernelInfo?.status === 'starting' || actionInFlight.start
    const isBusyStatus = isStarting || actionInFlight.stop || actionInFlight.restart
    const hasActionInFlight = Object.values(actionInFlight).some(Boolean)

    const isModalKernel = kernelInfo?.backend === 'modal'
    const selectedCpu = cpuCoreOptions[cpuIndex]
    const selectedMemory = memoryGbOptions[memoryIndex]
    const currentCpu = kernelInfo?.cpu_cores ?? selectedCpu
    const currentMemory = kernelInfo?.memory_gb ?? selectedMemory
    const currentIdleTimeout = kernelInfo?.idle_timeout_seconds ?? idleTimeoutOptions[1].value
    const hasConfigChanges =
        kernelInfo &&
        (Math.abs(selectedCpu - currentCpu) > 1e-6 ||
            Math.abs(selectedMemory - currentMemory) > 1e-6 ||
            idleTimeoutSeconds !== currentIdleTimeout)

    useEffect(() => {
        if (!kernelInfo) {
            return
        }
        setCpuIndex(findClosestOptionIndex(cpuCoreOptions, kernelInfo.cpu_cores))
        setMemoryIndex(findClosestOptionIndex(memoryGbOptions, kernelInfo.memory_gb))
        setIdleTimeoutSeconds(kernelInfo.idle_timeout_seconds ?? idleTimeoutOptions[1].value)
    }, [kernelInfo?.cpu_cores, kernelInfo?.memory_gb, kernelInfo?.idle_timeout_seconds])

    return (
        <LemonWidget
            className="NotebookColumn__widget"
            title="Kernel info"
            actions={
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => loadKernelInfo()}
                    loading={actionInFlight.refresh}
                    disabled={hasActionInFlight && !actionInFlight.refresh}
                >
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
                        {isBusyStatus ? <Spinner size="small" textColored /> : null}
                        <LemonTag type="default">{kernelInfo.backend === 'modal' ? 'Modal' : 'Local'}</LemonTag>
                        {kernelInfo.cpu_cores ? (
                            <LemonTag type="default">{formatCores(kernelInfo.cpu_cores)}</LemonTag>
                        ) : null}
                        {kernelInfo.memory_gb ? (
                            <LemonTag type="default">{formatMemory(kernelInfo.memory_gb)} RAM</LemonTag>
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
                            loading={actionInFlight.start || isStarting}
                            disabled={(hasActionInFlight && !actionInFlight.start) || isRunning}
                            disabledReason={isRunning ? 'Kernel already running' : undefined}
                        >
                            Start
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => stopKernel()}
                            loading={actionInFlight.stop}
                            disabled={(hasActionInFlight && !actionInFlight.stop) || !isRunning}
                            disabledReason={!isRunning ? 'Kernel is not running' : undefined}
                        >
                            Stop
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => restartKernel()}
                            loading={actionInFlight.restart}
                            disabled={hasActionInFlight && !actionInFlight.restart}
                        >
                            Restart
                        </LemonButton>
                    </div>
                    <div className="space-y-3 border-t border-border pt-3">
                        <div className="space-y-1">
                            <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                                Compute profile
                            </div>
                            <div className="text-xs text-muted">
                                CPU and RAM are reservations. Usage can burst above the configured values.
                            </div>
                        </div>
                        <div className="space-y-3">
                            <div className="space-y-1">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="font-semibold text-muted">CPU</span>
                                    <span className="font-semibold">{formatCores(selectedCpu)}</span>
                                </div>
                                <div className={!isModalKernel ? 'pointer-events-none opacity-50' : undefined}>
                                    <LemonSlider
                                        value={cpuIndex}
                                        min={0}
                                        max={cpuCoreOptions.length - 1}
                                        step={1}
                                        onChange={(value) => setCpuIndex(value)}
                                    />
                                </div>
                            </div>
                            <div className="space-y-1">
                                <div className="flex items-center justify-between text-xs">
                                    <span className="font-semibold text-muted">RAM</span>
                                    <span className="font-semibold">{formatMemory(selectedMemory)}</span>
                                </div>
                                <div className={!isModalKernel ? 'pointer-events-none opacity-50' : undefined}>
                                    <LemonSlider
                                        value={memoryIndex}
                                        min={0}
                                        max={memoryGbOptions.length - 1}
                                        step={1}
                                        onChange={(value) => setMemoryIndex(value)}
                                    />
                                </div>
                            </div>
                        </div>
                        <div className="space-y-1">
                            <div className="text-xs font-semibold text-muted uppercase tracking-wide">Idle timeout</div>
                            <LemonSelect
                                value={idleTimeoutSeconds}
                                options={idleTimeoutOptions}
                                onChange={(value) => setIdleTimeoutSeconds(value)}
                                size="small"
                                disabled={!isModalKernel}
                                disabledReason={
                                    !isModalKernel ? 'Scaling options are available for Modal kernels.' : undefined
                                }
                            />
                            <div className="text-xs text-muted">
                                Automatically stop after this period of inactivity.
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                size="small"
                                type="primary"
                                onClick={() =>
                                    saveKernelConfig({
                                        cpu_cores: selectedCpu,
                                        memory_gb: selectedMemory,
                                        idle_timeout_seconds: idleTimeoutSeconds,
                                    })
                                }
                                loading={actionInFlight.save}
                                disabled={!isModalKernel || !hasConfigChanges || hasActionInFlight}
                                disabledReason={
                                    !isModalKernel
                                        ? 'Scaling options are available for Modal kernels.'
                                        : hasConfigChanges
                                          ? undefined
                                          : 'No configuration changes to save'
                                }
                            >
                                Save changes
                            </LemonButton>
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => {
                                    setCpuIndex(findClosestOptionIndex(cpuCoreOptions, kernelInfo.cpu_cores))
                                    setMemoryIndex(findClosestOptionIndex(memoryGbOptions, kernelInfo.memory_gb))
                                    setIdleTimeoutSeconds(
                                        kernelInfo.idle_timeout_seconds ?? idleTimeoutOptions[1].value
                                    )
                                }}
                                disabled={!hasConfigChanges || hasActionInFlight}
                            >
                                Cancel
                            </LemonButton>
                        </div>
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
                                loading={actionInFlight.execute}
                                disabled={hasActionInFlight && !actionInFlight.execute}
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
