import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getLaravelSteps as getLaravelStepsPA } from '../product-analytics/laravel'
import { StepDefinition } from '../steps'

export const getLaravelSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, dedent, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    // Get installation steps from product-analytics
    const installationSteps = getLaravelStepsPA(ctx)

    // Add flag-specific steps (using PHP flag implementation)
    const flagSteps: StepDefinition[] = [
        {
            title: 'Evaluate boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Check if a feature flag is enabled:
                        `}
                    </Markdown>
                    {BooleanFlag && <BooleanFlag language="php" />}
                </>
            ),
        },
        {
            title: 'Evaluate multivariate feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For multivariate flags, check which variant the user has been assigned:
                        `}
                    </Markdown>
                    {MultivariateFlag && <MultivariateFlag language="php" />}
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

export const LaravelInstallation = createInstallation(getLaravelSteps)
