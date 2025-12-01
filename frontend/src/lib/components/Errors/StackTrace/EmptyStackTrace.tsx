import { useMemo } from 'react'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { ErrorTrackingException } from '../types'
import { KnownExceptionRegistry } from './known-exceptions'

export function EmptyStackTrace({ exception }: { exception: ErrorTrackingException }): JSX.Element {
    const knownIssue = useMemo(() => KnownExceptionRegistry.match(exception), [exception])
    if (knownIssue) {
        return knownIssue.render(exception)
    }
    return (
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
}
