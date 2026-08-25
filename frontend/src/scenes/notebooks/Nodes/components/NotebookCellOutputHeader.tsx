import { ReactNode } from 'react'

// Marks where a V2 cell's code stops and its output starts. A bare divider does not read as that
// boundary, because the node's title and its settings block already end on the same 1px line. The
// tint is what separates the two. `min-h-9` is a small LemonTabs bar plus this strip's padding, so
// the SQL cell's tabs and the Python cell's shorter label sit on strips of the same height.

type NotebookCellOutputHeaderProps = {
    /** Names the output below. Python cells pass a label, SQL cells pass their result tabs. */
    children: ReactNode
}

export function NotebookCellOutputHeader({ children }: NotebookCellOutputHeaderProps): JSX.Element {
    return (
        <div
            className="flex min-h-9 shrink-0 items-center gap-2 border-b border-primary bg-fill-highlight-50 px-2 py-1 text-xs text-muted"
            // Switching tabs is a click on node chrome, which otherwise expands or drags the node.
            onClick={(event) => event.stopPropagation()}
        >
            {children}
        </div>
    )
}
