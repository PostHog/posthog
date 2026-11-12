import { IconLightBulb } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { isHttpsUrl } from 'lib/utils/url'

export interface DidYouKnowAction {
    label: string
    url: string
}

export interface DidYouKnowPayload {
    title: string
    description: string
    action?: DidYouKnowAction
}

export interface DidYouKnowToastProps {
    payload: DidYouKnowPayload
    onActionClick?: () => void
}

export function DidYouKnowToast({ payload, onActionClick }: DidYouKnowToastProps): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col items-start gap-1 py-1 pr-1 text-default">
            <div className="flex items-center gap-1.5 text-sm font-semibold">
                <IconLightBulb className="size-4 shrink-0" />
                <span>{payload.title}</span>
            </div>
            <div className="text-xs leading-snug text-muted">{payload.description}</div>
            {payload.action && (
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    to={payload.action.url}
                    targetBlank={isHttpsUrl(payload.action.url)}
                    onClick={onActionClick}
                    data-attr="did-you-know-action"
                >
                    {payload.action.label}
                </LemonButton>
            )}
        </div>
    )
}
