import { Button, Spinner, Text } from '@posthog/quill'

interface TodayPaneStateProps {
    /** Shows a spinner in place of a message. */
    loading?: boolean
    message?: string
    /** Adds a "Try again" button that calls this. */
    onRetry?: () => void
    /** Shows the retry button as busy while the reload is in flight. */
    retrying?: boolean
    retryDataAttr?: string
}

/** The loading, empty or error state inside a sidebar list, sized to sit among its rows. */
export function TodayPaneState({
    loading = false,
    message,
    onRetry,
    retrying = false,
    retryDataAttr,
}: TodayPaneStateProps): JSX.Element {
    return (
        <div className="flex flex-col items-start gap-2 p-2">
            {loading ? (
                <Spinner />
            ) : (
                message && (
                    <Text size="xs" variant="muted">
                        {message}
                    </Text>
                )
            )}
            {onRetry && (
                <Button variant="outline" size="sm" loading={retrying} onClick={onRetry} data-attr={retryDataAttr}>
                    Try again
                </Button>
            )}
        </div>
    )
}
