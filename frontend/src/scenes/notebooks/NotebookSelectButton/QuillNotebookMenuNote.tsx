import type { ReactNode } from 'react'

/** A line of plain text in the notebook menu, such as an empty or loading state. It is not an item, so it takes no focus. */
export function QuillNotebookMenuNote({ children }: { children: ReactNode }): JSX.Element {
    return <div className="px-2 py-1.5 text-xs text-muted-foreground">{children}</div>
}
