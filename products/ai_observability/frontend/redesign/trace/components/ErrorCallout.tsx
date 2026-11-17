import { LemonBanner } from '@posthog/lemon-ui'

export interface ErrorCalloutProps {
    message: string
    onRetry?: () => void
}

export function ErrorCallout({ message, onRetry }: ErrorCalloutProps): JSX.Element {
    return (
        <LemonBanner type="error" action={onRetry ? { children: 'Try again', onClick: onRetry } : undefined}>
            <span className="font-mono text-sm whitespace-pre-wrap break-words">{message}</span>
        </LemonBanner>
    )
}
