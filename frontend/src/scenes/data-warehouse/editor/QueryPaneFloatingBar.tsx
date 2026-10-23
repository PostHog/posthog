/**
 * The bar that floats over the bottom of the query pane. Two of them share the spot and never
 * show together: the accept and reject pair for a suggested query, and the save pair for an
 * edited view. They have to look like one thing, so the position and chrome live here and each
 * caller brings only its own contents.
 */
export function QueryPaneFloatingBar({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            // The 2rem keeps a gutter on both sides, so a narrow pane wraps the contents rather
            // than running them past the edge.
            className="absolute bottom-4 left-1/2 z-10 max-w-[calc(100%-2rem)] -translate-x-1/2 rounded border bg-bg-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)' }}
        >
            {children}
        </div>
    )
}
