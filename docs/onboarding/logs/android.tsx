import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getAndroidSteps as getAndroidStepsPA } from '../product-analytics/android'
import { StepDefinition } from '../steps'

export const getAndroidSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getAndroidStepsPA(ctx)

    const sendLogStep: StepDefinition = {
        title: 'Send a log',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    Capture a structured log record with `PostHog.logger`. Requires `com.posthog:posthog-android` 3.46.0
                    or later. Records are batched and shipped to PostHog's logs product.
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                                import com.posthog.PostHog

                                PostHog.logger.info("Server started", mapOf(
                                    "server.port" to 3000,
                                    "server.env" to "production"
                                ))
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Logs appear in PostHog within a few seconds. Use the [Logs page](https://app.posthog.com/logs) to search and filter
                        by service name, severity, or any attribute you attach.
                    `}
                </Markdown>
            </>
        ),
    }

    return [...installSteps, sendLogStep]
}

export const AndroidInstallation = createInstallation(getAndroidSteps)
