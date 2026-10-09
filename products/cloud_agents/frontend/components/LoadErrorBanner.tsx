import { LemonBanner } from '@posthog/lemon-ui'

/** The error screen of a section: what did not load, and a button that loads it again. */
export function LoadErrorBanner({
    what,
    onRetry,
    retrying,
}: {
    /** The thing that did not load, as it reads after "Could not load". */
    what: string
    onRetry: () => void
    retrying?: boolean
}): JSX.Element {
    return (
        <LemonBanner
            type="error"
            action={{
                children: 'Try again',
                onClick: onRetry,
                loading: retrying,
                disabledReason: retrying ? 'Loading' : undefined,
            }}
        >
            Could not load {what}. Try again, and contact support if it keeps happening.
        </LemonBanner>
    )
}
