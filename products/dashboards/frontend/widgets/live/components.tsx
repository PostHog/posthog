import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard/WidgetCardBody'

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

export interface LiveWidgetEmptyStateProps {
    message: string
    cta?: {
        label: string
        to: string
        targetBlank?: boolean
        onClick?: () => void
    }
}

/** "No data in the real-time window yet" state for live widget tiles. */
export function LiveWidgetEmptyState({ message, cta }: LiveWidgetEmptyStateProps): JSX.Element {
    return (
        <WidgetCardContent>
            <WidgetCardBodyMessage>
                <div
                    className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                    data-attr="live-widget-empty-state"
                >
                    <p className="m-0 text-sm text-muted">{message}</p>
                    {cta ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            to={cta.to}
                            targetBlank={cta.targetBlank}
                            onClick={cta.onClick}
                        >
                            {cta.label}
                        </LemonButton>
                    ) : null}
                </div>
            </WidgetCardBodyMessage>
        </WidgetCardContent>
    )
}
