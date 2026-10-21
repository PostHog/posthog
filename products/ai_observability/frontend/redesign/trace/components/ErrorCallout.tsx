import { LemonBanner } from '@posthog/lemon-ui'

export interface ErrorCalloutProps {
    message: string
}

export function ErrorCallout({ message }: ErrorCalloutProps): JSX.Element {
    return (
        <LemonBanner type="error">
            <span className="font-mono text-sm whitespace-pre-wrap break-words">{message}</span>
        </LemonBanner>
    )
}
