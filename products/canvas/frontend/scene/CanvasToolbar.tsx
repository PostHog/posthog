/**
 * The bar across the top of a canvas page, like PostHog Desktop's ChromeBar. It is as tall as the app
 * side panel's tab bar, so the two borders meet.
 */
export function CanvasToolbar({
    children,
    actions,
    dataAttr,
}: {
    children: React.ReactNode
    actions?: React.ReactNode
    dataAttr: string
}): JSX.Element {
    return (
        <div
            className="@container/canvas-toolbar flex h-12.5 shrink-0 items-center gap-2 border-b border-border bg-chrome pr-2 pl-1"
            data-attr={dataAttr}
        >
            <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">{children}</div>
            {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
        </div>
    )
}
