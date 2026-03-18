import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { KnownException } from '../Exception/known-exceptions'
import { ErrorTrackingException } from '../types'

export function EmptyStackTrace({
    exception,
    knownException,
}: {
    exception: ErrorTrackingException
    knownException?: KnownException
}): JSX.Element {
    return (
        knownException?.render(exception) ?? (
            <div className="border-1 rounded">
                <EmptyMessage
                    title="No stacktrace available"
                    description="Make sure the SDK is set up correctly or contact support if problem persists"
                    buttonText="Check documentation"
                    buttonTo="https://posthog.com/docs/error-tracking/installation"
                    size="small"
                />
            </div>
        )
    )
}
