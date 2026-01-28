import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactSteps as getReactStepsPA } from '../product-analytics/react'
import { StepDefinition } from '../steps'

export const getReactSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, dedent, snippets } = ctx
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

    // Get installation steps from product-analytics only (exclude "Send events")
    const installationSteps = getReactStepsPA(ctx).filter(
        (step: StepDefinition) => step.title !== 'Send events'
    )

    // Add experiments-specific steps
    const experimentSteps: StepDefinition[] = [
        {
            title: 'Implement your experiment',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Experiments run on top of our feature flags. You can define which version of your code runs based on the return value of the feature flag.

                            You can use the \`useFeatureFlagVariantKey\` hook or the \`PostHogFeature\` component:
                        `}
                    </Markdown>
                    {ExperimentImplementation && <ExperimentImplementation language="react" />}
                </>
            ),
        },
        {
            title: 'Run your experiment',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        Once you've implemented the feature flag in your code, you'll enable it for a target audience by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]

    return [...installationSteps, ...experimentSteps]
}

export const ReactInstallation = createInstallation(getReactSteps)
