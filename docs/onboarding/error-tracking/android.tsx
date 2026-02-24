import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getAndroidSteps as getAndroidStepsPA } from '../product-analytics/android'
import { StepDefinition } from '../steps'

export const getAndroidSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const installSteps = getAndroidStepsPA(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <CalloutBox type="fyi" title="Client-side configuration only">
                    <Markdown>
                        {dedent`
                            This configuration is client-side only. Support for remote configuration 
                            in the [error tracking settings](https://app.posthog.com/settings/project-error-tracking#exception-autocapture) 
                            will be added in a future release.
                        `}
                    </Markdown>
                </CalloutBox>
                <Markdown>
                    {dedent`
                        You can autocapture exceptions by setting the \`errorTrackingConfig.autoCapture\` 
                        argument to \`true\` when initializing the PostHog SDK.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                              import com.posthog.android.PostHogAndroidConfig
                              val config = PostHogAndroidConfig(
                                  apiKey = POSTHOG_API_KEY,
                                  host = POSTHOG_HOST
                              ).apply {
                                  ...
                                  errorTrackingConfig.autoCapture = true
                              }
                              ...
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        When enabled, this automatically captures \`$exception\` events when errors are thrown by wrapping the \`Thread.UncaughtExceptionHandler\` listener.
                    `}
                </Markdown>
                <CalloutBox type="fyi" title="Planned features">
                    <Markdown>
                        {dedent`
                            We currently don't support [source code context](/docs/error-tracking/stack-traces.md) associated with an exception.

                            These features will be added in a future release.
                        `}
                    </Markdown>
                </CalloutBox>
            </>
        ),
    }

    const manualCaptureStep: StepDefinition = {
        title: 'Manually capture exceptions',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        It is also possible to manually capture exceptions using the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                              PostHog.captureException(
                                  exception,
                                  properties = additionalProperties
                              )
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        This is helpful if you've built your own error handling logic or want to capture exceptions that are handled by your application code.
                    `}
                </Markdown>
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Before proceeding, let's make sure exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                `}
            </Markdown>
        ),
    }

    return [
        ...installSteps,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
    ]
}

export const AndroidInstallation = createInstallation(getAndroidSteps)
