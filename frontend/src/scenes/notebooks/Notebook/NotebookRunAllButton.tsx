import { useActions, useValues } from 'kea'

import { IconPlay, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { isKernelUiEnabled } from '../utils'
import { isMarkdownNotebookContent } from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'
import { notebookRunLogic } from './notebookRunLogic'

/**
 * Runs every SQL and Python cell of the open notebook, in document order. While a run is
 * active the same button stops it, so the toolbar keeps one slot for the whole action.
 */
export const NotebookRunAllButton = (
    props: Pick<LemonButtonProps, 'children' | 'size' | 'type'>
): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { content, shortId, isShared, sqlV2NodeSummaries } = useValues(notebookLogic)
    const { isRunning, isStarting, isInterrupting, progressLabel } = useValues(notebookRunLogic({ shortId }))
    const { startRun, interruptRun } = useActions(notebookRunLogic({ shortId }))

    // Only a markdown notebook with something to run gets the button at all.
    if (!isKernelUiEnabled(featureFlags) || !isMarkdownNotebookContent(content) || !sqlV2NodeSummaries.length) {
        return null
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
