import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactSteps as getReactStepsPA } from '../product-analytics/react'
import { StepDefinition } from '../steps'

export const getReactSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getReactStepsPA(ctx)

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

    const errorBoundaryStep: StepDefinition = {
        title: 'Set up error boundaries',
        badge: 'optional',
        content: (
            <>
                <Markdown>
                    {dedent`
                        You can use the \`PostHogErrorBoundary\` component to capture rendering errors thrown by components:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'JavaScript',
                            code: dedent`
                                import { PostHogProvider, PostHogErrorBoundary } from '@posthog/react'
                                const Layout = () => {
                                  return (
                                    <PostHogProvider apiKey="<ph_project_api_key>">
                                      <PostHogErrorBoundary
                                        fallback={<YourFallbackComponent />} // (Optional) Add a fallback component that's shown when an error happens.
                                      >
                                        <YourApp />
                                      </PostHogErrorBoundary>
                                    </PostHogProvider>
                                  )
                                }
                                const YourFallbackComponent = ({ error, componentStack, exceptionEvent }) => {
                                  return <div>Something went wrong. Please try again later.</div>
                                }
                            `,
                        },
                    ]}
                />
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
        errorBoundaryStep,
        manualCaptureStep,
        verifyStep,
    ]
}

export const ReactInstallation = createInstallation(getReactSteps)
