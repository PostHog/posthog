import { LemonButton } from '@posthog/lemon-ui'

export function FeedbackButton({ id }: { id: string }): JSX.Element {
    return (
        <LemonButton size="small" id={id} tooltip="Have any questions or feedback?">
            Feedback
        </LemonButton>
    )
}
