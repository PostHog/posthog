import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNodeJSSteps as getNodeJSStepsPA } from '../product-analytics/nodejs'
import { StepDefinition } from '../steps'

export const getNodeJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, dedent, snippets } = ctx
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

    // Get installation steps from product-analytics only (exclude "Send an event")
    const installationSteps = getNodeJSStepsPA(ctx).filter((step: StepDefinition) => step.title !== 'Send an event')

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

                            **Note:** Server-side experiment metrics require you to manually send the feature flag information. See [this tutorial](https://posthog.com/docs/experiments/adding-experiment-code) for more information.
                        `}
                    </Markdown>
                    {ExperimentImplementation && <ExperimentImplementation language="node.js" />}
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

export const NodeJSInstallation = createInstallation(getNodeJSSteps)
