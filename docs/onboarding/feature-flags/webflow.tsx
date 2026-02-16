import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getWebflowSteps as getWebflowStepsPA } from '../product-analytics/webflow'
import { StepDefinition } from '../steps'

export const getWebflowSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, dedent, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    // Get installation steps from product-analytics
    const installationSteps = getWebflowStepsPA(ctx)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Use boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Check if a feature flag is enabled:
                        `}
                    </Markdown>
                    {BooleanFlag && <BooleanFlag language="javascript" />}
                </>
            ),
        },
        {
            title: 'Use multivariate feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For multivariate flags, check which variant the user has been assigned:
                        `}
                    </Markdown>
                    {MultivariateFlag && <MultivariateFlag language="javascript" />}
                </>
            ),
        },
        {
            title: 'Running experiments',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an experiment by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]

    return [...installationSteps, ...flagSteps]
}

export const WebflowInstallation = createInstallation(getWebflowSteps)
