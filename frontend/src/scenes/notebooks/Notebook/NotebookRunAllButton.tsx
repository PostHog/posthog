import { useActions, useValues } from 'kea'

import { IconPlay, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { notebookNodeSQLV2Logic } from '../Nodes/notebookNodeSQLV2Logic'
import { isKernelUiEnabled } from '../utils'
import { notebookKernelProviderLogic } from './browserKernel/notebookKernelProviderLogic'
import { isMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import { notebookNodeStalenessLogic } from './notebookNodeStalenessLogic'
import { notebookRunLogic } from './notebookRunLogic'

/**
 * Runs every SQL and Python cell of the open notebook, in document order. While a run is
 * active the same button stops it, so the toolbar keeps one slot for the whole action.
 */
export const NotebookRunAllButton = (
    props: Pick<LemonButtonProps, 'children' | 'size' | 'type'>
): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { content, shortId, isShared, runnableCellNodeIds } = useValues(notebookLogic)
    const { isRunning, isStarting, isInterrupting, progressLabel } = useValues(notebookRunLogic({ shortId }))
    const { startRun, interruptRun } = useActions(notebookRunLogic({ shortId }))
    const { provider } = useValues(notebookKernelProviderLogic({ shortId }))
    const { isChainRunning, isRunAllChain, chainQueue } = useValues(notebookNodeStalenessLogic({ shortId }))
    const { runAllChain, abortChain } = useActions(notebookNodeStalenessLogic({ shortId }))

    // Only a markdown notebook with something to run gets the button at all. Runnable means
    // SQL or Python, the same pair the backend plan walks — a notebook of Python cells alone
    // runs perfectly well, and reading the SQL summaries hid the button from it.
    if (!isKernelUiEnabled(featureFlags) || !isMarkdownNotebookContent(content) || !runnableCellNodeIds.length) {
        return null
    }

    // A backend run would send Python to a sandbox, so a browser notebook runs its cells from this tab.
    if (provider === 'browser') {
        if (isChainRunning && isRunAllChain) {
            return (
                <LemonButton
                    {...props}
                    onClick={() => {
                        const runningNodeId = chainQueue[0]
                        abortChain(null)
                        if (runningNodeId) {
                            notebookNodeSQLV2Logic.findMounted({ nodeId: runningNodeId })?.actions.interruptRun()
                        }
                    }}
                    icon={<IconStopFilled />}
                    tooltip="Stop the run"
                    data-attr="notebook-run-all-stop"
                >
                    Stop
                </LemonButton>
            )
        }
        return (
            <LemonButton
                {...props}
                onClick={() => runAllChain(content, runnableCellNodeIds)}
                icon={<IconPlay />}
                disabledReason={
                    isShared
                        ? 'You can only run cells in the notebook itself'
                        : isChainRunning
                          ? 'Cells are already running'
                          : undefined
                }
                tooltip="Run every SQL and Python cell in order, stopping at the first one that fails"
                data-attr="notebook-run-all"
            >
                Run all
            </LemonButton>
        )
    }

    if (isRunning) {
        return (
            <LemonButton
                {...props}
                onClick={() => interruptRun()}
                icon={<IconStopFilled />}
                loading={isInterrupting}
                disabledReason={isInterrupting ? 'Stopping the run' : undefined}
                tooltip={progressLabel ?? 'Stop the run'}
                data-attr="notebook-run-all-stop"
            >
                Stop
            </LemonButton>
        )
    }

    return (
        <LemonButton
            {...props}
            onClick={() => startRun()}
            icon={<IconPlay />}
            loading={isStarting}
            disabledReason={
                isShared ? 'You can only run cells in the notebook itself' : isStarting ? 'Starting the run' : undefined
            }
            tooltip="Run every SQL and Python cell in order, stopping at the first one that fails"
            data-attr="notebook-run-all"
        >
            Run all
        </LemonButton>
    )
}
