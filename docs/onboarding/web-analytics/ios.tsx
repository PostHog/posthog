import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getIOSInstallSteps } from '../product-analytics/ios'
import { StepDefinition } from '../steps'

export const getIOSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    return [
        ...getIOSInstallSteps(ctx),
        {
            title: 'Track screen views',
            badge: 'recommended' as const,
            content: (
                <>
                    {MobileFinalSteps && <MobileFinalSteps />}
                    <Markdown>To automatically track screen views, configure PostHog to capture screen views:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'swift',
                                file: 'AppDelegate.swift',
                                code: dedent`
                                        let config = PostHogConfig(projectToken: POSTHOG_PROJECT_TOKEN, host: POSTHOG_HOST)
                                        config.captureScreenViews = true
                                        PostHogSDK.shared.setup(config)
                                    `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const IOSInstallation = createInstallation(getIOSSteps)
