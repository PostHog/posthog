/** Pulsing "Live" marker shown in a live widget tile's header top-heading row. */
export function LiveWidgetIndicator(): JSX.Element {
    return (
        <span className="flex items-center gap-1 font-medium text-success" data-attr="live-widget-indicator">
            <span className="relative flex size-2" aria-hidden>
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success opacity-75" />
                <span className="relative inline-flex size-2 rounded-full bg-success" />
            </span>
            Live
        </span>
    )
}
