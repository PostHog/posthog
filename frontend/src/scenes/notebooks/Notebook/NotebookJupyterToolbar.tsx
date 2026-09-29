import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconFastForward, IconKeyboard, IconPlayFilled, IconPlus, IconRefresh, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { useNotebookJupyterCommands, useNotebookJupyterStoreValue } from 'lib/components/MarkdownNotebook/jupyterMode'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import { notebookJupyterLogic } from './notebookJupyterLogic'
import { NotebookJupyterShortcutsModal } from './NotebookJupyterShortcutsModal'
import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import { notebookLogic } from './notebookLogic'
import { notebookRunLogic } from './notebookRunLogic'

export function NotebookJupyterToolbar(): JSX.Element | null {
    const jupyter = useNotebookJupyterCommands()
    const { shortId, isShared } = useValues(notebookLogic)
    const { statusInfo, isStarting } = useValues(notebookKernelInfoLogic({ shortId, isShared }))
    const { isRunning: isRunAllRunning } = useValues(notebookRunLogic({ shortId }))
    const { interruptRun: interruptRunAll } = useActions(notebookRunLogic({ shortId }))
    const { isRestartingKernel } = useValues(notebookJupyterLogic({ shortId }))
    const { requestKernelRestart } = useActions(notebookJupyterLogic({ shortId }))
    const activeNodeId = useNotebookJupyterStoreValue((state) => state.activeNodeId)
    const activeRunHandler = useNotebookJupyterStoreValue((state) =>
        state.activeNodeId ? (state.runHandlers.get(state.activeNodeId) ?? null) : null
    )
    const runningHandler = useNotebookJupyterStoreValue(
        (state) => [...state.runHandlers.values()].find((handler) => handler.isRunning) ?? null
    )

    if (!jupyter) {
        return null
    }

    const isActiveCell = !!activeNodeId && jupyter.isCellNode(activeNodeId)
    const noCellReason = 'Select a cell first'
    const isBusy = !!runningHandler || isRunAllRunning || isRestartingKernel || isStarting
    const kernelStatus = isRestartingKernel
        ? 'Restarting'
        : isBusy
          ? 'Busy'
          : !statusInfo || statusInfo.label === 'Running'
            ? 'Idle'
            : statusInfo.label

    const runActiveCell = (): void => {
        if (!activeNodeId || !activeRunHandler || activeRunHandler.disabledReason) {
            return
        }
        activeRunHandler.run()
        jupyter.advanceFromCell(activeNodeId)
    }

    const interrupt = (): void => {
        if (isRunAllRunning) {
            interruptRunAll()
            return
        }
        const handler = activeRunHandler?.isRunning ? activeRunHandler : runningHandler
        handler?.interrupt?.()
    }

    return (
        <>
            <div
                className="NotebookJupyterToolbar sticky top-0 z-10 flex flex-wrap items-center gap-0.5 py-1 mb-2 border-b bg-surface-primary"
                // Keeps focus, and with it command mode, on the selected cell while a button is clicked.
                onMouseDown={(event) => event.preventDefault()}
                data-attr="notebook-jupyter-toolbar"
            >
                <LemonButton
                    size="small"
                    icon={<IconPlus />}
                    tooltip="Insert a cell below (B)"
                    aria-label="Insert a cell below"
                    onClick={() => jupyter.insertCell(activeNodeId, 'below', { edit: true })}
                    data-attr="notebook-jupyter-insert-cell"
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowUp />}
                    tooltip="Move the selected cell up"
                    aria-label="Move the selected cell up"
                    disabledReason={isActiveCell ? undefined : noCellReason}
                    onClick={() => activeNodeId && jupyter.moveCell(activeNodeId, 'up')}
                />
                <LemonButton
                    size="small"
                    icon={<IconArrowDown />}
                    tooltip="Move the selected cell down"
                    aria-label="Move the selected cell down"
                    disabledReason={isActiveCell ? undefined : noCellReason}
                    onClick={() => activeNodeId && jupyter.moveCell(activeNodeId, 'down')}
                />
                <LemonDivider vertical className="mx-1 h-5" />
                <LemonButton
                    size="small"
                    icon={<IconPlayFilled />}
                    tooltip="Run the selected cell and select the next one (Shift+Enter)"
                    aria-label="Run the selected cell"
                    disabledReason={
                        !isActiveCell ? noCellReason : (activeRunHandler?.disabledReason ?? undefined) || undefined
                    }
                    onClick={runActiveCell}
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
                    value={isActiveCell ? 'code' : activeNodeId ? 'markdown' : null}
                    placeholder="-"
                    options={[
                        { value: 'code', label: 'Code' },
                        { value: 'markdown', label: 'Markdown' },
                    ]}
                    disabledReason={isActiveCell ? undefined : 'Select a code cell to change its type'}
                    onChange={(value) => {
                        if (value === 'markdown' && activeNodeId) {
                            jupyter.convertCellToMarkdown(activeNodeId)
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
                <Tooltip title={`Kernel status: ${kernelStatus}`}>
                    <div className="flex items-center gap-2 px-2 text-xs text-secondary whitespace-nowrap">
                        <span>Python 3 (sandbox)</span>
                        <span
                            aria-label={`Kernel ${kernelStatus.toLowerCase()}`}
                            className={clsx(
                                'inline-block size-3 rounded-full border-2 border-current',
                                isBusy && 'bg-current'
                            )}
                        />
                    </div>
                </Tooltip>
            </div>
            <NotebookJupyterShortcutsModal />
        </>
    )
}
