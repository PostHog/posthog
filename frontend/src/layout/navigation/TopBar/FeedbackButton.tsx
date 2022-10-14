import { LemonButton } from 'lib/components/LemonButton'
import React from 'react'

export function FeedbackButton(): JSX.Element {
    return (
        <LemonButton data-attr={`posthog-feedback-button`}>
            <span className="text-default grow">Feedback</span>
        </LemonButton>
    )
}
