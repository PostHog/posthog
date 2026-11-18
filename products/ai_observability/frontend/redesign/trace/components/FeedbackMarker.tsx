import { IconMessage } from '@posthog/icons'

export interface FeedbackMarkerProps {
    count: number
}

export function FeedbackMarker({ count }: FeedbackMarkerProps): JSX.Element {
    return (
        <span
            className="flex shrink-0 items-center gap-0.5 text-xs font-normal text-secondary"
            role="img"
            aria-label={`Feedback: ${count}`}
            title={`Feedback: ${count}`}
        >
            <IconMessage />
            <span>{count}</span>
        </span>
    )
}
