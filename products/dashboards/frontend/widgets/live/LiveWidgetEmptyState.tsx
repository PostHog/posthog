import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard'

export interface LiveWidgetEmptyStateProps {
    message: string
    cta?: {
        label: string
        to: string
        targetBlank?: boolean
        onClick?: () => void
    }
    dataAttr?: string
}

/** "No data in the real-time window yet" state for live widget tiles. */
export function LiveWidgetEmptyState({ message, cta, dataAttr }: LiveWidgetEmptyStateProps): JSX.Element {
    return (
        <WidgetCardContent>
            <WidgetCardBodyMessage>
                <div
                    className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                    data-attr={dataAttr ?? 'live-widget-empty-state'}
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
