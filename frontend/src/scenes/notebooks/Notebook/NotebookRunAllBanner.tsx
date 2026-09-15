import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { notebookRunLogic } from './notebookRunLogic'

/**
 * Progress for a whole-notebook run, above the document. Styled like the downstream-run banner
 * on a cell, because it is the same kind of nudge rather than an error state.
 */
export const NotebookRunAllBanner = ({ shortId }: { shortId: string }): JSX.Element | null => {
    const { isRunning, progressLabel } = useValues(notebookRunLogic({ shortId }))
    const { interruptRun } = useActions(notebookRunLogic({ shortId }))

    if (!isRunning) {
        return null
    }

    return (
        <div className="mx-2 mt-1 flex flex-wrap items-center gap-2 rounded border border-accent bg-accent-highlight-secondary p-2 text-xs">
            <Spinner textColored />
            <span>{progressLabel ?? 'Starting the run'}</span>
            <LemonButton
                type="secondary"
                size="xsmall"
                onClick={() => interruptRun()}
                data-attr="notebook-run-all-banner-stop"
            >
                Stop
            </LemonButton>
        </div>
    )
}
