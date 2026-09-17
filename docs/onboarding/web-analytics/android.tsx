import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getAndroidInstallSteps } from '../product-analytics/android'
import { StepDefinition } from '../steps'

export const getAndroidSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    return [
        ...getAndroidInstallSteps(ctx),
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
                                language: 'kotlin',
                                file: 'SampleApp.kt',
                                code: dedent`
                                        val config = PostHogAndroidConfig(
                                            apiKey = POSTHOG_PROJECT_TOKEN,
                                            host = POSTHOG_HOST
                                        ).apply {
                                            captureScreenViews = true
                                        }
                                        PostHogAndroid.setup(this, config)
                                    `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const AndroidInstallation = createInstallation(getAndroidSteps)
