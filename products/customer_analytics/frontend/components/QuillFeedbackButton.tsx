import { Button } from '@posthog/quill'

export function QuillFeedbackButton({ id }: { id: string }): JSX.Element {
    return (
        <Button id={id} tooltip="Have any questions or feedback?">
            Feedback
        </Button>
    )
}
