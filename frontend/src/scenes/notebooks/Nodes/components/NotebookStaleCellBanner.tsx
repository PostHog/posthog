import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import type { NotebookStaleReason } from '../../Notebook/notebookNodeStalenessLogic'

const REASON_CAUSE: Record<NotebookStaleReason, string> = {
    upstream: 'an upstream cell has re-run',
    variable: 'a notebook variable changed',
}

// Journey 10: shown on a V2 cell whose inputs moved on after it last ran. Identification only:
// the action to re-run lives on the cell that caused the staleness (NotebookRunDownstreamBanner).
export function NotebookStaleCellBanner({ reason = 'upstream' }: { reason?: NotebookStaleReason }): JSX.Element {
    return (
        <LemonBanner type="warning" className="mx-2 mt-1 p-2 text-xs" hideIcon>
            These results may be out of date because {REASON_CAUSE[reason]}. Run this cell to refresh its output data.
        </LemonBanner>
    )
}
