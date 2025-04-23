import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { FingerprintRecordPart } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { ExceptionAttributes } from 'scenes/error-tracking/utils'

export interface StacktraceBaseDisplayProps {
    className?: string
    truncateMessage: boolean

    loading: boolean
    renderLoading: () => JSX.Element
    renderEmpty: () => JSX.Element

    attributes: ExceptionAttributes

    showAllFrames: boolean
}

export interface StacktraceBaseExceptionHeaderProps {
    type?: string
    value?: string
    loading: boolean
    runtime?: ErrorTrackingRuntime
    part?: FingerprintRecordPart
    truncate: boolean
}

export function StacktraceEmptyDisplay(): JSX.Element {
    return (
        <EmptyMessage
            title="No stacktrace available"
            description="Make sure sdk is setup correctly or contact support if problem persists"
            buttonText="Check documentation"
            buttonTo="https://posthog.com/docs/error-tracking/installation"
            size="small"
        />
    )
}
