import { useValues } from 'kea'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'

import { errorPropertiesLogic } from '../errorPropertiesLogic'
import { ErrorTrackingException } from '../types'

export function EmptyStacktraceDisplay({ exception }: { exception: ErrorTrackingException }): JSX.Element {
    const { knownIssue } = useValues(errorPropertiesLogic)
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
