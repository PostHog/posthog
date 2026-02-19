import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAndroidSteps as getAndroidStepsPA } from '../product-analytics/android'
import { StepDefinition } from '../steps'

export const getAndroidSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    // Get installation steps from product-analytics
    const paSteps = getAndroidStepsPA(ctx)

    // Replace the "Send events" step with web analytics specific content
    const webAnalyticsSteps = paSteps.map((step) => {
        if (step.title === 'Send events') {
            return {
                title: 'Track screen views',
                badge: 'recommended' as const,
                content: (
                    <>
                        {MobileFinalSteps && <MobileFinalSteps />}
                        <Markdown>
                            To automatically track screen views, configure PostHog to capture screen views:
                        </Markdown>
                        <CodeBlock
                            blocks={[
                                {
                                    language: 'kotlin',
                                    file: 'SampleApp.kt',
                                    code: dedent`
                                        val config = PostHogAndroidConfig(
                                            apiKey = POSTHOG_API_KEY,
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
            }
        }
        return step
    })

    return webAnalyticsSteps
}

export const AndroidInstallation = createInstallation(getAndroidSteps)
