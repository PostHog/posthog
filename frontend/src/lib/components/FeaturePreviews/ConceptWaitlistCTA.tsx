import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export interface ConceptWaitlistCTAProps {
    feature: EnrichedEarlyAccessFeature
    size?: 'small' | 'medium'
    /** Frozen once shipped: autocapture dashboards and Playwright select on it. */
    dataAttr?: string
    /** Skipped for impersonated sessions, where the sign-up itself is refused. */
    onSignUp?: () => void
    /** Off: one-click sign-up tied to the logged-in account, even when the feature links a waitlist survey. */
    collectEmail?: boolean
}

export function ConceptWaitlistCTA({
    feature,
    size = 'small',
    dataAttr,
    onSignUp,
    collectEmail = true,
}: ConceptWaitlistCTAProps): JSX.Element {
    const { waitlistSurveysEnabled, conceptSurveySubmissions } = useValues(featurePreviewsLogic)
    const { submitConceptSurvey, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const [email, setEmail] = useState('')

    const { flagKey, enabled } = feature

    const hasWaitlistSurvey = collectEmail && waitlistSurveysEnabled && !!feature.payload?.survey_id

    const notifySignUp = (): void => {
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
                    notifySignUp()
                }}
                size={size}
                sideIcon={enabled ? <IconCheck /> : <IconBell />}
                className="w-fit"
                data-attr={dataAttr}
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
                    notifySignUp()
                }
            }}
        >
            <LemonInput
                type="email"
                value={email}
                onChange={setEmail}
                placeholder="email@yourcompany.com"
                // Several concept features can render this form on one page; name whose it is.
                aria-label={`Email address to join the ${feature.name} waitlist`}
                autoComplete="email"
                size={size}
            />
            <LemonButton
                type="primary"
                size={size}
                htmlType="submit"
                disabledReason={!email ? 'Enter your email' : undefined}
                aria-label={`Get notified when ${feature.name} is ready`}
                data-attr={dataAttr}
            >
                Get notified
            </LemonButton>
        </form>
    )
}
