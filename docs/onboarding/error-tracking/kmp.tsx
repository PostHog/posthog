import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getKMPSteps } from '../product-analytics/kmp'
import { StepDefinition } from '../steps'

export const getKMPErrorTrackingSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    const installSteps = getKMPSteps(ctx)

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'recommended',
        content: (
            <>
                <CalloutBox type="fyi" title="Version requirement">
                    <Markdown>The error tracking configuration requires PostHog KMP version 0.4.0 or higher.</Markdown>
                </CalloutBox>
                <Markdown>
                    Set `errorTracking.autoCapture` to `true` when you initialize PostHog. You can also provide package
                    or bundle prefixes so PostHog marks matching stack frames as in-app code.
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                                import com.posthog.kmp.ErrorTrackingConfig
                                import com.posthog.kmp.PostHogConfig

                                val config = PostHogConfig(
                                    apiKey = "<ph_project_token>",
                                    host = "<ph_client_api_host>",
                                    errorTracking = ErrorTrackingConfig(
                                        autoCapture = true,
                                        inAppIncludes = listOf("com.example"),
                                    ),
                                )
                            `,
                        },
                    ]}
                />
                <Markdown>
                    On Android, iOS, and JVM, this captures unhandled exceptions. On Kotlin/JS and Kotlin/Wasm, it
                    captures unhandled errors and unhandled promise rejections. It does not capture browser console
                    errors.
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
                    Call `PostHog.captureException` for handled exceptions or errors caught by your application code.
                    You can include additional properties to help investigate the exception.
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                                try {
                                    riskyOperation()
                                } catch (error: Exception) {
                                    PostHog.captureException(
                                        throwable = error,
                                        additionalProperties = mapOf("context" to "checkout_flow"),
                                    )
                                }
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
                Capture a test exception, flush queued events with `PostHog.flush()`, and confirm the exception appears
                in [Error tracking](https://app.posthog.com/error_tracking). Unhandled mobile crashes are persisted and
                sent after the app launches again.
            </Markdown>
        ),
    }

    return [...installSteps, exceptionAutocaptureStep, manualCaptureStep, verifyStep]
}

export const KMPErrorTrackingInstallation = createInstallation(getKMPErrorTrackingSteps)
