import { LemonTag } from '@posthog/lemon-ui'

export interface TraceStatusBadgeProps {
    hasError: boolean
}

export function TraceStatusBadge({ hasError }: TraceStatusBadgeProps): JSX.Element {
    return hasError ? (
        <LemonTag type="danger" size="small">
            Error
        </LemonTag>
    ) : (
        <LemonTag size="small">Trace</LemonTag>
    )
}
