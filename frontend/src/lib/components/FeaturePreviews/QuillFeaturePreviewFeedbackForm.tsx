import { useActions, useAsyncActions, useValues } from 'kea'
import { useState } from 'react'

import { Button, Field, FieldLabel, Textarea } from '@posthog/quill'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export interface QuillFeaturePreviewFeedbackFormProps {
    feature: EnrichedEarlyAccessFeature
}

/** Mounts only while the feedback panel is open, so the draft resets when it closes. */
export function QuillFeaturePreviewFeedbackForm({ feature }: QuillFeaturePreviewFeedbackFormProps): JSX.Element {
    const { activeFeedbackFlagKeyLoading } = useValues(featurePreviewsLogic)
    const { cancelEarlyAccessFeatureFeedback } = useActions(featurePreviewsLogic)
    const { submitEarlyAccessFeatureFeedback } = useAsyncActions(featurePreviewsLogic)
    const [feedback, setFeedback] = useState('')

    const textareaId = `${feature.flagKey}-feedback`
    // A failed submit keeps the panel open (activeFeedbackFlagKey is unchanged), so the text survives for a retry
    const submit = (): void => {
        // Cmd+Enter reaches here without the Submit button's disabled checks
        if (!feedback.trim() || activeFeedbackFlagKeyLoading) {
            return
        }
        void submitEarlyAccessFeatureFeedback(feedback)
    }

    return (
        <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                submit()
            }}
        >
            <Field>
                <FieldLabel htmlFor={textareaId}>Your feedback</FieldLabel>
                <Textarea
                    id={textareaId}
                    autoFocus
                    placeholder={`What's your experience with ${feature.name} been like?`}
                    value={feedback}
                    onChange={(event) => setFeedback(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && event.metaKey) {
                            submit()
                        } else if (event.key === 'Escape') {
                            cancelEarlyAccessFeatureFeedback()
                            event.stopPropagation() // Don't close the modal
                        }
                    }}
                />
            </Field>
            <div className="flex flex-wrap justify-end gap-2">
                <Button variant="outline" onClick={() => cancelEarlyAccessFeatureFeedback()}>
                    Cancel
                </Button>
                <Button
                    type="submit"
                    variant="primary"
                    loading={activeFeedbackFlagKeyLoading}
                    disabledReason={!feedback.trim() ? 'Write your feedback first' : undefined}
                    data-attr="feature-preview-submit-feedback"
                >
                    Submit feedback
                </Button>
            </div>
        </form>
    )
}
