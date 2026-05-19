import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getWordpressSteps as getWordpressStepsPA } from '../product-analytics/wordpress'
import { StepDefinition } from '../steps'

export const getWordpressSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getWordpressStepsPA(ctx)

    // Add a "Send events" step at the end
    const webAnalyticsSteps: StepDefinition[] = [
        ...paSteps,
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    {WebFinalSteps && <WebFinalSteps />}
                    <Markdown>
                        See the [WordPress integration docs](https://posthog.com/docs/libraries/wordpress) for more
                        details on tracking events.
                    </Markdown>
                </>
            ),
        },
    ]

    return webAnalyticsSteps
}

export const WordpressInstallation = createInstallation(getWordpressSteps)
