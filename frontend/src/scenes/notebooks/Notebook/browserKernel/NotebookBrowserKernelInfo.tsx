import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import { LemonWidget } from 'lib/lemon-ui/LemonWidget'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { notebookLogic } from '../notebookLogic'
import { notebookSettingsLogic } from '../notebookSettingsLogic'
import { PYODIDE_VERSION } from './browserKernelProtocol'
import { BrowserKernelStatus, notebookBrowserKernelLogic } from './notebookBrowserKernelLogic'

const STATUS_TAGS: Record<BrowserKernelStatus, { label: string; type: LemonTagType }> = {
    stopped: { label: 'Stopped', type: 'default' },
    starting: { label: 'Starting', type: 'warning' },
    ready: { label: 'Ready', type: 'success' },
    busy: { label: 'Running', type: 'warning' },
    error: { label: 'Error', type: 'danger' },
}

/** The kernel panel for a notebook that runs Python in the browser. */
export function NotebookBrowserKernelInfo(): JSX.Element {
    const { shortId } = useValues(notebookLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)
    const { status, error, progress, frames, isRunning, canInterrupt } = useValues(
        notebookBrowserKernelLogic({ shortId })
    )
    const { startKernel, restartKernel, stopKernel } = useActions(notebookBrowserKernelLogic({ shortId }))
    const tag = STATUS_TAGS[status]

    return (
        <LemonWidget
            className="NotebookColumn__widget"
            title="Browser kernel"
            onClose={() => setShowKernelInfo(false)}
            actions={
                isRunning || status === 'starting' ? (
                    <div className="flex gap-1">
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => restartKernel()}
                            tooltip="Clears every variable and dataframe"
                            data-attr="notebook-browser-kernel-panel-restart"
                        >
                            Restart
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={() => stopKernel()}
                            data-attr="notebook-browser-kernel-panel-stop"
                        >
                            Stop
                        </LemonButton>
                    </div>
                ) : (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => startKernel()}
                        data-attr="notebook-browser-kernel-panel-start"
                    >
                        Start
                    </LemonButton>
                )
            }
        >
            <div className="space-y-3 p-3 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonTag type={tag.type}>{tag.label}</LemonTag>
                    <LemonTag type="default">Pyodide {PYODIDE_VERSION}</LemonTag>
                    <LemonTag type="default">pandas + DuckDB</LemonTag>
                </div>
                {status === 'starting' || progress ? (
                    <div className="flex items-center gap-2 text-secondary">
                        <Spinner textColored />
                        {progress ?? 'Starting Python'}
                    </div>
                ) : null}
                {error ? <div className="text-danger">{error}</div> : null}
                <div className="text-secondary">
                    Python runs in this tab, so nothing is charged and no sandbox starts. Variables live until you
                    reload or close the notebook. Each SQL result a cell reads is capped at 50,000 rows.
                </div>
                <div className="text-secondary">
                    Cells can import numpy, scipy, matplotlib, scikit-learn and other packages Pyodide ships, and
                    install pure Python packages with <code>await micropip.install('name')</code>.
                    {canInterrupt ? null : ' Stopping a running cell restarts the kernel.'}
                </div>
                <div className="space-y-1">
                    <div className="font-semibold text-secondary">Dataframes and tables</div>
                    {frames.length ? (
                        <ul className="m-0 p-0 list-none space-y-1">
                            {frames.map((frame) => (
                                <li key={frame.name} className="flex items-center justify-between gap-2">
                                    <code className="truncate">{frame.name}</code>
                                    <span className="text-secondary shrink-0">
                                        {frame.row_count == null
                                            ? `${frame.columns.length} columns`
                                            : `${humanFriendlyNumber(frame.row_count)} rows, ${frame.columns.length} columns`}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <div className="text-secondary">
                            {isRunning
                                ? 'None yet. Run a Python cell to create one.'
                                : 'Start the kernel or run a cell to load data.'}
                        </div>
                    )}
                </div>
            </div>
        </LemonWidget>
    )
}
