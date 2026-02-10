import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getDocusaurusSteps as getDocusaurusStepsPA } from '../product-analytics/docusaurus'
import { StepDefinition } from '../steps'

export const getDocusaurusSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getDocusaurusStepsPA(ctx)

    // Replace the "View events" step with web analytics specific content
    const webAnalyticsSteps = paSteps.map((step) => {
        if (step.title === 'View events') {
            return {
                title: 'Send events',
                badge: 'recommended' as const,
                content: (
                    <>
                        <Markdown>
                            Start your Docusaurus site and visit a few pages. PostHog will automatically capture
                            pageviews and other events.
                        </Markdown>
                        {WebFinalSteps && <WebFinalSteps />}
                    </>
                ),
            }
        }
        return step
    })

    return webAnalyticsSteps
}

export const DocusaurusInstallation = createInstallation(getDocusaurusSteps)
