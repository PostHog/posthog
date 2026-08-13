import { ReactNode } from 'react'

// Separates a V2 cell's output from the code above it: the output sits in its own card on a
// recessed ground, under a header strip. Without it the first line of output reads as another
// line of the editor, because a 1px divider looks the same as the one under the node's title.

type NotebookCellOutputFrameProps = {
    /** Header strip content. Defaults to an "Output" label; SQL cells pass their result tabs. */
    header?: ReactNode
    children: ReactNode
}

export function NotebookCellOutputFrame({ header, children }: NotebookCellOutputFrameProps): JSX.Element {
    return (
        <div
            className="flex min-h-0 flex-1 flex-col overflow-hidden border-t border-primary bg-fill-highlight-75 p-2"
            // Paging, switching tabs, and selecting a cell value are all clicks on node chrome that
            // otherwise expands or drags the node.
            onClick={(event) => event.stopPropagation()}
        >
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded border border-primary bg-surface-primary">
                <div className="flex shrink-0 items-center justify-between gap-2 border-b border-primary bg-fill-highlight-50 px-2 text-xs text-muted">
                    {header ?? <span className="py-1">Output</span>}
                </div>
                {/* A flex column, not a plain scroll box: the SQL cell's chart sizes itself from
                    `flex-1`, so the chain from the node's content down to it has to stay unbroken. */}
                <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
            </div>
        </div>
    )
}
