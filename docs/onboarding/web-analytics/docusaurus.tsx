import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getDocusaurusInstallSteps } from '../product-analytics/docusaurus'
import { StepDefinition } from '../steps'

export const getDocusaurusSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, snippets } = ctx
    const WebFinalSteps = snippets?.WebFinalSteps

    return [
        ...getDocusaurusInstallSteps(ctx),
        {
            title: 'Send events',
            badge: 'recommended' as const,
            content: (
                <>
                    <Markdown>
                        Start your Docusaurus site and visit a few pages. PostHog will automatically capture pageviews
                        and other events.
                    </Markdown>
                    {WebFinalSteps && <WebFinalSteps />}
                </>
            ),
        },
    ]
}

export const DocusaurusInstallation = createInstallation(getDocusaurusSteps)
