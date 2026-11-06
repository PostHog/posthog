import { useActions, useValues } from 'kea'

import { Button, Field, FieldLabel, Input } from '@posthog/quill'

import { StepLayout } from '../components/StepLayout'
import { guidedOnboardingLogic } from '../guidedOnboardingLogic'

export function ProjectStep(): JSX.Element {
    const { resolvedProjectName } = useValues(guidedOnboardingLogic)
    const { setProjectName, next } = useActions(guidedOnboardingLogic)

    return (
        <StepLayout
            title="What's your product called?"
            description="This becomes the name of your PostHog project."
            primary={
                <Button
                    variant="primary"
                    onClick={next}
                    disabledReason={!resolvedProjectName.trim() ? 'Enter a name' : undefined}
                    data-attr="guided-onboarding-project-continue"
                >
                    Continue
                </Button>
            }
        >
            <Field>
                <FieldLabel htmlFor="guided-onboarding-project-name">Product name</FieldLabel>
                <Input
                    id="guided-onboarding-project-name"
                    autoFocus
                    placeholder="Acme"
                    value={resolvedProjectName}
                    onChange={(event) => setProjectName(event.target.value)}
                    onKeyDown={(event) => event.key === 'Enter' && resolvedProjectName.trim() && next()}
                    data-attr="guided-onboarding-project-name"
                />
            </Field>
        </StepLayout>
    )
}
