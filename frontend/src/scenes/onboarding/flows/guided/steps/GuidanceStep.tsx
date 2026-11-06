import { useActions, useValues } from 'kea'

import { IconCompass, IconWrench } from '@posthog/icons'

import { ChoiceList } from '../components/ChoiceList'
import { StepLayout } from '../components/StepLayout'
import { type Guidance, guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function GuidanceStep(): JSX.Element {
    const { guidance } = useValues(guidedOnboardingLogic)
    const { setGuidance } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout title="How do you want to set up PostHog?" description="You can change anything later.">
            <ChoiceList<Guidance>
                choices={[
                    {
                        value: 'guided',
                        title: 'Guide me',
                        description: 'Answer 5 short questions. We set PostHog up around one goal for your product.',
                        icon: <IconCompass />,
                    },
                    {
                        value: 'self',
                        title: "I'll set it up myself",
                        description: 'Go straight to installing PostHog.',
                        icon: <IconWrench />,
                    },
                ]}
                selected={guidance}
                onSelect={setGuidance}
                dataAttrPrefix="guided-onboarding-guidance"
            />
        </StepLayout>
    )
}
