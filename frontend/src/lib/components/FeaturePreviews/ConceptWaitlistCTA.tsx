import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export interface ConceptWaitlistCTAProps {
    feature: EnrichedEarlyAccessFeature
    size?: 'small' | 'medium'
    /** Runs after a sign-up the backend will accept, for callers that record their own product intent. */
    onSignUp?: () => void
}

/** Waitlist sign-up for a concept ("Coming soon") early access feature. */
export function ConceptWaitlistCTA({ feature, size = 'small', onSignUp }: ConceptWaitlistCTAProps): JSX.Element {
    const { waitlistSurveysEnabled, conceptSurveySubmissions } = useValues(featurePreviewsLogic)
    const { submitConceptSurvey, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const [email, setEmail] = useState('')

    const { flagKey, enabled } = feature

    // When the gate is on and the feature has a linked waitlist survey, collect an email
    // (recorded as a survey response) instead of the one-click, login-tied enrollment.
    const hasWaitlistSurvey = waitlistSurveysEnabled && !!feature.payload?.survey_id

    const signUp = (): void => {
        // submitConceptSurvey and the enrollment listener both refuse impersonated sessions, so
        // skip the callback too: a rejected sign-up must not record a false adoption signal.
        if (!window.IMPERSONATED_SESSION) {
            onSignUp?.()
        }
    }

    if (!hasWaitlistSurvey) {
        return (
            <LemonButton
                type="primary"
                disabledReason={
                    enabled && "You have already expressed your interest. We'll contact you when it's ready"
                }
                onClick={() => {
                    updateEarlyAccessFeatureEnrollment(flagKey, true, feature.stage)
                    signUp()
                }}
                size={size}
                sideIcon={enabled ? <IconCheck /> : <IconBell />}
                className="w-fit"
            >
                {enabled ? 'Registered' : 'Get notified'}
            </LemonButton>
        )
    }

    // `enabled` covers users who registered interest before the survey era. The migration
    // command moves them into the survey, so do not ask them again.
    if (!!conceptSurveySubmissions[flagKey] || enabled) {
        // role="status" makes the confirmation a live region: the form (and its focused
        // button) unmounts on submit, so without it screen readers announce nothing.
        return (
            <span role="status" className="flex items-center gap-1 text-success font-medium">
                <IconCheck /> Thanks, we'll email you when it's ready.
            </span>
        )
    }

    return (
        <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
                e.preventDefault()
                if (email) {
                    submitConceptSurvey(flagKey, email)
                    signUp()
                }
            }}
        >
            <LemonInput
                type="email"
                value={email}
                onChange={setEmail}
                placeholder="email@yourcompany.com"
                aria-label="Email address"
                autoComplete="email"
                size={size}
            />
            <LemonButton
                type="primary"
                size={size}
                htmlType="submit"
                disabledReason={!email ? 'Enter your email' : undefined}
            >
                Get notified
            </LemonButton>
        </form>
    )
}
