import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'

export interface InsightLoadErrorProps {
    /** HTTP status the request came back with, or `null` when the request never got a response. */
    status: number | null
    onRetry: () => void
}

export function InsightLoadError({ status, onRetry }: InsightLoadErrorProps): JSX.Element {
    useOnMountEffect(() => {
        posthog.capture('insight_load_error_shown', { status })
    })

    const handleRetry = (): void => {
        posthog.capture('insight_load_error_retried', { status })
        onRetry()
    }

    return (
        <div
            className="flex flex-col items-center max-w-2xl p-4 mx-auto my-24 text-center"
            data-attr="insight-load-error"
        >
            <h1 className="text-2xl font-bold mt-4 mb-0">Couldn't load this insight</h1>
            <p className="text-sm mt-3 mb-0">
                {status !== null
                    ? `The server returned an error (HTTP ${status}).`
                    : 'The request to the server failed.'}{' '}
                Your insight is still saved. Try again, and if it keeps happening contact support.
            </p>
            <LemonButton className="mt-4" type="primary" onClick={handleRetry} data-attr="insight-load-error-retry">
                Try again
            </LemonButton>
        </div>
    )
}
