import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput, LemonModal, LemonSwitch, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { urls } from 'scenes/urls'

import { buildThumbSurveySnippet } from '../feedbackSurvey'
import { feedbackSurveyModalLogic } from '../feedbackSurveyModalLogic'

const USE_THUMB_SURVEY_DOCS_URL = 'https://posthog.com/docs/ai-observability/user-feedback/use-thumb-survey'
const MANUAL_CAPTURE_DOCS_URL = 'https://posthog.com/docs/ai-observability/user-feedback/manual-event-capture'

export function FeedbackSurveyModal(): JSX.Element {
    const { isOpen, createdSurvey, feedbackSurvey, isFeedbackSurveySubmitting } = useValues(feedbackSurveyModalLogic)
    const { closeModal, submitFeedbackSurvey } = useActions(feedbackSurveyModalLogic)

    if (createdSurvey) {
        return (
            <LemonModal
                isOpen={isOpen}
                onClose={closeModal}
                title="Add the survey to your app"
                width={640}
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            to={urls.survey(createdSurvey.id)}
                            data-attr="trace-view-feedback-survey-view"
                        >
                            View survey
                        </LemonButton>
                        <LemonButton type="primary" onClick={closeModal}>
                            Done
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-3">
                    <p className="m-0">
                        <strong>{createdSurvey.name}</strong> is live. It shows nothing until your code calls it. In a
                        React app, wire it to your thumbs buttons with <code>useThumbSurvey</code> and pass the trace
                        id, so each response shows on that trace's Feedback tab.
                    </p>
                    <CodeSnippet language={Language.JSX} thing="snippet">
                        {buildThumbSurveySnippet(createdSurvey.id)}
                    </CodeSnippet>
                    <p className="m-0 text-secondary">
                        Needs posthog-js 1.345.1 or later.{' '}
                        <Link to={USE_THUMB_SURVEY_DOCS_URL} target="_blank">
                            useThumbSurvey docs
                        </Link>
                        {' · '}
                        <Link to={MANUAL_CAPTURE_DOCS_URL} target="_blank">
                            Not using React? Send the events yourself
                        </Link>
                    </p>
                </div>
            </LemonModal>
        )
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Create a feedback survey"
            description="Ask users for a thumbs up or down on AI responses. Responses show on the trace they rate."
            width={560}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitFeedbackSurvey}
                        loading={isFeedbackSurveySubmitting}
                        data-attr="trace-view-feedback-survey-create"
                    >
                        Create & continue
                    </LemonButton>
                </>
            }
        >
            <Form logic={feedbackSurveyModalLogic} formKey="feedbackSurvey" className="flex flex-col gap-4">
                <LemonField
                    name="name"
                    label="Survey name"
                    help="Make one survey per AI feature, so you can review each feature's feedback on its own."
                >
                    <LemonInput data-attr="trace-view-feedback-survey-name" />
                </LemonField>
                <LemonField name="followUpEnabled">
                    {({ value, onChange }) => (
                        <LemonSwitch
                            checked={!!value}
                            onChange={onChange}
                            label="Ask follow-up on thumbs down"
                            bordered
                            fullWidth
                        />
                    )}
                </LemonField>
                {feedbackSurvey.followUpEnabled ? (
                    <LemonField name="followUpQuestion" label="Follow-up question">
                        <LemonInput />
                    </LemonField>
                ) : null}
                <p className="m-0 text-secondary">
                    The survey goes live right away. As an API survey, it never pops up on its own, only where your code
                    shows it. You can change it later in Surveys.
                </p>
            </Form>
        </LemonModal>
    )
}
