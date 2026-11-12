import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBell, IconCheck } from '@posthog/icons'
import { Button, Input, Text } from '@posthog/quill'

import { hasConceptWaitlistSurvey, hasJoinedConceptWaitlist } from './ConceptWaitlistCTA'
import { EnrichedEarlyAccessFeature, featurePreviewsLogic } from './featurePreviewsLogic'

export interface QuillConceptWaitlistCTAProps {
    feature: EnrichedEarlyAccessFeature
}

export function QuillConceptWaitlistCTA({ feature }: QuillConceptWaitlistCTAProps): JSX.Element {
    const { waitlistSurveysEnabled, conceptSurveySubmissions } = useValues(featurePreviewsLogic)
    const { submitConceptSurvey, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    const [email, setEmail] = useState('')

    const { flagKey, enabled } = feature

    if (!hasConceptWaitlistSurvey(feature, waitlistSurveysEnabled)) {
        return (
            <Button
                variant="primary"
                size="sm"
                disabledReason={
                    enabled ? "You have already expressed your interest. We'll contact you when it's ready" : undefined
                }
                onClick={() => updateEarlyAccessFeatureEnrollment(flagKey, true, feature.stage)}
            >
                {enabled ? <IconCheck /> : <IconBell />}
                {enabled ? 'Registered' : 'Get notified'}
            </Button>
        )
    }

    if (hasJoinedConceptWaitlist(feature, conceptSurveySubmissions)) {
        // A live region, because the focused submit button unmounts on submit
        return (
            <Text size="xs" weight="medium" render={<span role="status" />} className="flex items-center gap-1">
                <IconCheck />
                Thanks, we'll email you when it's ready.
            </Text>
        )
    }

    return (
        <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                if (email) {
                    submitConceptSurvey(flagKey, email)
                }
            }}
        >
            <Input
                type="email"
                size="sm"
                className="min-w-48 flex-1"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="email@yourcompany.com"
                // Several concept features can render this form on one page; name whose it is.
                aria-label={`Email address to join the ${feature.name} waitlist`}
                autoComplete="email"
            />
            <Button
                type="submit"
                variant="primary"
                size="sm"
                disabledReason={!email ? 'Enter your email' : undefined}
                aria-label={`Get notified when ${feature.name} is ready`}
            >
                Get notified
            </Button>
        </form>
    )
}
