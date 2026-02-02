import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getJSWebSteps as getJSWebStepsPA } from '../product-analytics/js-web'
import { StepDefinition } from '../steps'

export const getJSWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getJSWebStepsPA(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    {dedent`
                        You can enable exception autocapture for the JavaScript Web SDK in the **Error tracking** section of [your project settings](https://app.posthog.com/settings/project-error-tracking#exception-autocapture).

                        When enabled, this automatically captures \`$exception\` events when errors are thrown by wrapping the \`window.onerror\` and \`window.onunhandledrejection\` listeners.
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
                        It is also possible to manually capture exceptions using the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'JavaScript',
                            code: dedent`
                                posthog.captureException(error, additionalProperties)
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
                    Confirm exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

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

export const JSWebInstallation = createInstallation(getJSWebSteps)
