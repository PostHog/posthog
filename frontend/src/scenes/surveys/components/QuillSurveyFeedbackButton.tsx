import { Button } from '@posthog/quill'

export function QuillSurveyFeedbackButton(): JSX.Element {
    return (
        <Button id="surveys-page-feedback-button" tooltip="Have any questions or feedback?">
            Feedback
        </Button>
    )
}
