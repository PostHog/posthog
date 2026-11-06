import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { StepLayout } from '../components/StepLayout'
import { goalSentence } from '../focusOptions'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function DoneStep(): JSX.Element {
    const { focus, resolvedTarget, displayName } = useValues(guidedOnboardingLogic)
    const { finish } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout
            title={`${displayName} is ready`}
            description={
                focus?.custom
                    ? `Your goal: ${focus.metric}`
                    : focus
                      ? `Your goal is to ${goalSentence(focus, resolvedTarget).toLowerCase()}.`
                      : 'Your events show up in PostHog as soon as they arrive.'
            }
            primary={
                <Button variant="primary" onClick={finish} data-attr="guided-onboarding-finish">
                    Go to PostHog
                </Button>
            }
        />
    )
}
