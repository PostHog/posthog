import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

// Journey 10: shown on a V2 cell whose upstream re-ran after it. Identification only: the
// action to re-run lives in the notebook-level NotebookStaleCellsBanner, because the chain
// always runs the whole stale set rather than anything specific to this cell.
export function NotebookStaleCellBanner(): JSX.Element {
    return (
        <LemonBanner type="warning" className="mx-2 mt-1 p-2 text-xs" hideIcon>
            These results are out of date. A cell this one depends on has re-run. Run this cell again to see fresh data.
        </LemonBanner>
    )
}
