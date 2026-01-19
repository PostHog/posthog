import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonTag, Popover } from '@posthog/lemon-ui'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'

import { cpuCoreOptions, idleTimeoutOptions, memoryGbOptions, notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import { notebookLogic } from './notebookLogic'
import { notebookSettingsLogic } from './notebookSettingsLogic'

const formatCores = (value: number): string => {
    const formatted = value % 1 === 0 ? value.toString() : value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '')
    return `${formatted}x`
}

const formatMemory = (value: number): string => {
    if (value < 1) {
        return `${Math.round(value * 1024)} MB`
    }
    return `${value} GB`
}

const CPU_PRICE_PER_CORE_HOUR = 0.1419
const MEMORY_PRICE_PER_GIB_HOUR = 0.0242

const formatHourlyPrice = (value: number): string => `$${value.toFixed(2)} / h`

export const NotebookKernelInfo = (): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const logic = notebookKernelInfoLogic({ shortId })
    useAttachedLogic(logic, notebookLogic)
    const {
        kernelInfo,
        kernelInfoLoading,
        executionResult,
        actionInFlight,
        isRunning,
        statusInfo,
        isStarting,
        hasActionInFlight,
        isModalKernel,
        selectedCpu,
        selectedMemory,
        idleTimeoutSeconds,
        hasConfigChanges,
        code,
        cpuIndex,
        memoryIndex,
    } = useValues(logic)
    const {
        clearExecution,
        executeKernel,
        loadKernelInfo,
        restartKernel,
        saveKernelConfig,
        startKernel,
        stopKernel,
        setCode,
        setCpuIndex,
        setMemoryIndex,
        setIdleTimeoutSeconds,
        resetConfigToKernel,
    } = useActions(logic)
    const showLoadingState = kernelInfoLoading && !kernelInfo

    const isDockerKernel = kernelInfo?.backend === 'docker'
    const startActionLabel = isRunning ? 'Restart' : 'Start'
    const kernelInfoDetails =
        kernelInfo?.last_used_at || kernelInfo?.kernel_id || kernelInfo?.kernel_pid || kernelInfo?.sandbox_id ? (
            <div className="space-y-1 text-xs p-2">
                <div className="mb-2">CPU and RAM are reservations. Usage can burst above the configured values.</div>
                {kernelInfo.kernel_id ? <div>Kernel ID: {kernelInfo.kernel_id}</div> : null}
                {kernelInfo.kernel_pid ? <div>Kernel PID: {kernelInfo.kernel_pid}</div> : null}
                {kernelInfo.sandbox_id ? <div>Sandbox: {kernelInfo.sandbox_id}</div> : null}
                {kernelInfo.last_used_at ? <div>Last used: {kernelInfo.last_used_at}</div> : null}
            </div>
        ) : null
    const startOrRestartKernel = (): void => {
        if (isModalKernel && hasConfigChanges) {
            saveKernelConfig(
                {
                    cpu_cores: selectedCpu,
                    memory_gb: selectedMemory,
                    idle_timeout_seconds: idleTimeoutSeconds,
                },
                isRunning ? 'restart' : 'start'
            )
            return
        }
        if (isRunning) {
            restartKernel()
            return
        }
        startKernel()
    }
    const startActionInFlight = actionInFlight.start || actionInFlight.restart || actionInFlight.save || isStarting
    const [isOpen, setIsOpen] = useState(false)

    return (
        <LemonWidget
            className="NotebookColumn__widget"
            title={
                <div className="flex gap-1">
                    Kernel info
                    {kernelInfoDetails ? (
                        <Popover overlay={kernelInfoDetails} visible={isOpen} placement="bottom">
                            <LemonButton
                                icon={<IconInfo className="text-base" />}
                                size="xsmall"
                                type="tertiary"
                                noPadding
                                onClick={() => setIsOpen(true)}
                                onMouseEnter={() => setIsOpen(true)}
                                onMouseLeave={() => setIsOpen(false)}
                            />
                        </Popover>
                    ) : null}
                </div>
            }
            onClose={() => setShowKernelInfo(false)}
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
            {showLoadingState ? (
                <div className="flex items-center gap-2 text-muted text-sm p-3">
                    <Spinner textColored />
                    Loading kernel status
                </div>
            ) : kernelInfo ? (
                <div className="space-y-3 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                            {statusInfo ? <LemonTag type={statusInfo.tone}>{statusInfo.label}</LemonTag> : null}
                            <LemonTag type="default">
                                {kernelInfo.backend === 'modal' ? 'Modal' : 'Local - Docker'}
                            </LemonTag>
                            {kernelInfo.cpu_cores && !isDockerKernel ? (
                                <LemonTag type="default">{formatCores(kernelInfo.cpu_cores)}</LemonTag>
                            ) : null}
                            {kernelInfo.memory_gb && !isDockerKernel ? (
                                <LemonTag type="default">{formatMemory(kernelInfo.memory_gb)} RAM</LemonTag>
                            ) : null}
                            {kernelInfo.disk_size_gb && !isDockerKernel ? (
                                <LemonTag type="default">{kernelInfo.disk_size_gb} GB disk</LemonTag>
                            ) : null}
                        </div>
                        <div className="flex items-center gap-2 text-xs">
                            {isModalKernel ? (
                                <span className="font-semibold">
                                    {formatHourlyPrice(
                                        selectedCpu * CPU_PRICE_PER_CORE_HOUR +
                                            selectedMemory * MEMORY_PRICE_PER_GIB_HOUR
                                    )}
                                </span>
                            ) : null}
                        </div>
                    </div>
                    {kernelInfo.last_error ? (
                        <div className="text-xs text-danger">Error: {kernelInfo.last_error}</div>
                    ) : null}
                    {isModalKernel ? (
                        <div className="space-y-3">
                            <div className="space-y-3">
                                <div className="space-y-1">
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="font-semibold text-muted">CPU </span>
                                        <span className="font-semibold">{formatCores(selectedCpu)} </span>
                                    </div>
                                    <LemonSlider
                                        value={cpuIndex}
                                        min={0}
                                        max={cpuCoreOptions.length - 1}
                                        step={1}
                                        onChange={(value) => setCpuIndex(value)}
                                    />
                                </div>
                                <div className="space-y-1">
                                    <div className="flex items-center justify-between text-xs">
                                        <span className="font-semibold text-muted">RAM</span>
                                        <span className="font-semibold">{formatMemory(selectedMemory)}</span>
                                    </div>
                                    <LemonSlider
                                        value={memoryIndex}
                                        min={0}
                                        max={memoryGbOptions.length - 1}
                                        step={1}
                                        onChange={(value) => setMemoryIndex(value)}
                                    />
                                </div>
                            </div>
                            <div className="space-y-1 flex w-full justify-between items-center">
                                <div>
                                    <div className="text-xs font-semibold text-muted uppercase tracking-wide">
                                        Idle timeout
                                    </div>
                                    <div className="text-xs text-muted">
                                        Automatically stop after this period of inactivity.
                                    </div>
                                </div>
                                <LemonSelect
                                    value={idleTimeoutSeconds}
                                    options={idleTimeoutOptions}
                                    onChange={(value) => setIdleTimeoutSeconds(value)}
                                    size="small"
                                />
                            </div>
                        </div>
                    ) : (
                        <div className="text-sm text-muted">
                            Using docker-based local kernel. Can't update compute profile.
                        </div>
                    )}
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            size="small"
                            type="primary"
                            onClick={startOrRestartKernel}
                            loading={startActionInFlight}
                            disabled={hasActionInFlight && !startActionInFlight}
                        >
                            {startActionLabel}
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
                        {isModalKernel && hasConfigChanges ? (
                            <LemonButton
                                size="small"
                                type="secondary"
                                onClick={() => {
                                    resetConfigToKernel()
                                }}
                                disabled={hasActionInFlight}
                            >
                                Discard changes
                            </LemonButton>
                        ) : null}
                    </div>
                    <div className="space-y-3 border-t border-border pt-3">
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
