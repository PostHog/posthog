import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getKMPSteps as getKMPStepsPA } from '../product-analytics/kmp'
import { StepDefinition } from '../steps'

export const getKMPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, dedent, snippets } = ctx
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

    // Get installation steps from product-analytics only
    const installationSteps = getKMPStepsPA(ctx).filter((step: StepDefinition) => step.title !== 'Send events')

    // Add experiments-specific steps
    const experimentSteps: StepDefinition[] = [
        {
            title: 'Implement your experiment',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Experiments run on top of our feature flags. You can define which version of your code runs based on the return value of the feature flag:
                        `}
                    </Markdown>
                    {ExperimentImplementation && <ExperimentImplementation language="kmp" />}
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

export const KMPInstallation = createInstallation(getKMPSteps)
