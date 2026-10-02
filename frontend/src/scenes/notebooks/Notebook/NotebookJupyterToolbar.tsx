import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconFastForward, IconKeyboard, IconPlayFilled, IconPlus, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect } from '@posthog/lemon-ui'

import { useNotebookJupyterCommands, useNotebookJupyterStoreValue } from 'lib/components/MarkdownNotebook/jupyterMode'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { notebookJupyterLogic } from './notebookJupyterLogic'
import { NotebookJupyterShortcutsModal } from './NotebookJupyterShortcutsModal'
import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import { notebookLogic } from './notebookLogic'
import { notebookRunLogic } from './notebookRunLogic'
import { notebookSettingsLogic } from './notebookSettingsLogic'

export function NotebookJupyterToolbar(): JSX.Element | null {
    const jupyter = useNotebookJupyterCommands()
    const { shortId, isShared } = useValues(notebookLogic)
    const { statusInfo, isStarting } = useValues(notebookKernelInfoLogic({ shortId, isShared }))
    const { isRunning: isRunAllRunning } = useValues(notebookRunLogic({ shortId }))
    const { interruptRun: interruptRunAll } = useActions(notebookRunLogic({ shortId }))
    const { isRestartingKernel } = useValues(notebookJupyterLogic({ shortId }))
    const { requestKernelRestart } = useActions(notebookJupyterLogic({ shortId }))
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const activeCellId = useNotebookJupyterStoreValue((state) => state.activeCellId)
    const activeRunHandler = useNotebookJupyterStoreValue((state) =>
        state.activeCellId ? (state.runHandlers.get(state.activeCellId) ?? null) : null
    )
    const runningHandler = useNotebookJupyterStoreValue(
        (state) => [...state.runHandlers.values()].find((handler) => handler.isRunning && !handler.isQueued) ?? null
    )

    if (!jupyter) {
        return null
    }

    const activeCellKind = jupyter.getCellKind(activeCellId)
    const isActiveCell = activeCellKind === 'code'
    const noCellReason = 'Select a cell first'
    const isBusy = !!runningHandler || isRunAllRunning || isRestartingKernel || isStarting
    const kernelStatus = isRestartingKernel
        ? 'Restarting'
        : isBusy
          ? 'Busy'
          : !statusInfo || statusInfo.label === 'Running'
            ? 'Idle'
            : statusInfo.label

    const interrupt = (): void => {
        if (isRunAllRunning) {
            interruptRunAll()
            return
        }
        const handler = activeRunHandler?.isRunning && !activeRunHandler.isQueued ? activeRunHandler : runningHandler
        handler?.interrupt?.()
    }

    return (
        <>
            <div
                className="NotebookJupyterToolbar sticky top-0 z-10 flex flex-wrap items-center gap-0.5 py-1 mb-2 border rounded-xs bg-(--jupyter-paper-background)"
                // Keeps focus, and with it command mode, on the selected cell while a button is clicked.
                onMouseDown={(event) => event.preventDefault()}
                data-attr="notebook-jupyter-toolbar"
            >
                <LemonButton
                    size="small"
                    icon={<IconPlus />}
                    tooltip="Insert a cell below (B)"
                    aria-label="Insert a cell below"
                    onClick={() => jupyter.insertCell(activeCellId, 'below', { edit: true })}
                    data-attr="notebook-jupyter-insert-cell"
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowUp />}
                    tooltip="Move the selected cell up"
                    aria-label="Move the selected cell up"
                    disabledReason={activeCellKind ? undefined : noCellReason}
                    onClick={() => jupyter.executeCommand('move-up', activeCellId)}
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowDown />}
                    tooltip="Move the selected cell down"
                    aria-label="Move the selected cell down"
                    disabledReason={activeCellKind ? undefined : noCellReason}
                    onClick={() => jupyter.executeCommand('move-down', activeCellId)}
                />
                <LemonDivider vertical className="mx-1 h-5" />
                <LemonButton
                    size="small"
                    icon={<IconPlayFilled />}
                    tooltip="Run the selected cell and select the next one (Shift+Enter)"
                    aria-label="Run the selected cell"
                    disabledReason={
                        !activeCellKind
                            ? noCellReason
                            : isActiveCell
                              ? (activeRunHandler?.disabledReason ?? undefined) || undefined
                              : undefined
                    }
                    onClick={() => jupyter.executeCommand('run-and-advance', activeCellId)}
                    data-attr="notebook-jupyter-run-cell"
                />
                <LemonButton
                    size="small"
                    icon={<IconStopFilled />}
                    tooltip="Interrupt the kernel (I, I)"
                    aria-label="Interrupt the kernel"
                    disabledReason={runningHandler || isRunAllRunning ? undefined : 'Nothing is running'}
                    onClick={interrupt}
                    data-attr="notebook-jupyter-interrupt"
                />
                <LemonButton
                    size="small"
                    icon={<IconRefresh />}
                    tooltip="Restart the kernel (0, 0)"
                    aria-label="Restart the kernel"
                    disabledReason={isRestartingKernel ? 'The kernel is restarting' : undefined}
                    onClick={() => requestKernelRestart()}
                />
                <LemonButton
                    size="small"
                    icon={<IconFastForward />}
                    tooltip="Restart the kernel and run all cells"
                    aria-label="Restart the kernel and run all cells"
                    disabledReason={
                        isRestartingKernel
                            ? 'The kernel is restarting'
                            : isRunAllRunning
                              ? 'All cells are already running'
                              : undefined
                    }
                    onClick={() => requestKernelRestart(true)}
                />
                <LemonDivider vertical className="mx-1 h-5" />
                <LemonSelect
                    size="small"
                    value={activeCellKind === 'code' ? 'code' : activeCellKind === 'markdown' ? 'markdown' : null}
                    placeholder="-"
                    options={[
                        { value: 'code', label: 'Code' },
                        { value: 'markdown', label: 'Markdown' },
                    ]}
                    disabledReason={
                        activeCellKind === 'code' || activeCellKind === 'markdown'
                            ? undefined
                            : 'Select a code or markdown cell to change its type'
                    }
                    onChange={(value) => {
                        if (value && value !== activeCellKind) {
                            jupyter.executeCommand(value === 'markdown' ? 'to-markdown' : 'to-code', activeCellId)
                        }
                    }}
                    data-attr="notebook-jupyter-cell-type"
                />
                <div className="flex-1" />
                <LemonButton
                    size="small"
                    icon={<IconKeyboard />}
                    tooltip="Keyboard shortcuts (H)"
                    aria-label="Keyboard shortcuts"
                    onClick={() => jupyter.store.setShortcutsOpen(true)}
                    data-attr="notebook-jupyter-shortcuts"
                />
                <LemonButton
                    size="small"
                    tooltip={`Kernel status: ${kernelStatus}. Click to ${showKernelInfo ? 'hide' : 'show'} kernel details.`}
                    active={showKernelInfo}
                    onClick={() => setShowKernelInfo(!showKernelInfo)}
                    data-attr="notebook-jupyter-kernel-status"
                >
                    <span className="flex items-center gap-2 text-xs text-secondary font-normal whitespace-nowrap">
                        <span>Python 3 (sandbox)</span>
                        <span
                            aria-label={`Kernel ${kernelStatus.toLowerCase()}`}
                            className={clsx(
                                'inline-block size-3 rounded-full border-2 border-current',
                                isBusy && 'bg-current'
                            )}
                        />
                    </span>
                </LemonButton>
            </div>
            <NotebookJupyterShortcutsModal />
        </>
    )
}
