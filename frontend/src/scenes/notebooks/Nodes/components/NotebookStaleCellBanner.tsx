import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

// Journey 10: shown on a V2 cell whose upstream re-ran after it. Identification only: the
// action to re-run lives on the cell that caused the staleness (NotebookRunDownstreamBanner).
export function NotebookStaleCellBanner(): JSX.Element {
    return (
        <LemonBanner type="warning" className="mx-2 mt-1 p-2 text-xs" hideIcon>
            These results may be out of date because an upstream cell has re-run. Run this cell to refresh its output
            data.
        </LemonBanner>
    )
}
