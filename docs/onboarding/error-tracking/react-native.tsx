import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactNativeSteps as getReactNativeStepsPA } from '../product-analytics/react-native'
import { StepDefinition } from '../steps'

export const getReactNativeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const installSteps = getReactNativeStepsPA(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <CalloutBox type="fyi" title="Client-side configuration only">
                    <Markdown>
                        {dedent`
                            This configuration is client-side only. Support for remote configuration in the [error tracking settings](https://app.posthog.com/settings/project-error-tracking#exception-autocapture) will be added in a future release.
                        `}
                    </Markdown>
                </CalloutBox>
                <Markdown>
                    {dedent`
                        You can autocapture exceptions by configuring the \`errorTracking\` when setting up PostHog:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'jsx',
                            file: 'React Native',
                            code: dedent`
                              export const posthog = new PostHog('<ph_project_api_key>', {
                                errorTracking: {
                                  autocapture: {
                                    uncaughtExceptions: true,
                                    unhandledRejections: true,
                                    console: ['error', 'warn'],
                                  },
                                },
                              })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        **Configuration options:**

                        | Option | Description |
                        | --- | --- |
                        | \`uncaughtExceptions\` | Captures Uncaught exceptions (\`ReactNativeGlobal.ErrorUtils.setGlobalHandler\`) |
                        | \`unhandledRejections\` | Captures Unhandled rejections (\`ReactNativeGlobal.onunhandledrejection\`) |
                        | \`console\` | Captures console logs as errors according to the reported \`LogLevel\` |
                    `}
                </Markdown>
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
                        You can manually capture exceptions using the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'jsx',
                            file: 'React Native',
                            code: dedent`
                              try {
                                // Your awesome code that may throw
                                someRiskyOperation();
                              } catch (error) {
                                posthog.captureException(error)
                              }
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

    const futureFeaturesStep: StepDefinition = {
        title: 'Future features',
        badge: 'optional',
        content: (
            <Markdown>
                {dedent`
                    We currently don't support the following features:

                    - No native Android and iOS exception capture
                    - No automatic source map uploads on React Native web

                    These features will be added in future releases. We recommend you stay up to date with the latest version of the PostHog React Native SDK.
                `}
            </Markdown>
        ),
    }

    return [
        ...installSteps,
        exceptionAutocaptureStep,
        manualCaptureStep,
        verifyStep,
        futureFeaturesStep,
    ]
}

export const ReactNativeInstallation = createInstallation(getReactNativeSteps)
