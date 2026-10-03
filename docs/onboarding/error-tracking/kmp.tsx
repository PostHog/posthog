import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getKMPSteps } from '../product-analytics/kmp'
import { StepDefinition } from '../steps'

export const getKMPErrorTrackingSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, Tab, dedent } = ctx

    const installSteps = getKMPSteps(ctx)

    const enableExceptionAutocaptureStep: StepDefinition = {
        title: 'Enable exception autocapture in PostHog',
        badge: 'required',
        content: (
            <Markdown>
                In your project's [Error Tracking
                settings](https://app.posthog.com/settings/project-error-tracking#exception-autocapture), enable
                **Enable exception autocapture**. This project setting acts as a server-side kill switch, so the SDK
                does not automatically capture exceptions when it is disabled.
            </Markdown>
        ),
    }

    const exceptionAutocaptureStep: StepDefinition = {
        title: 'Set up exception autocapture',
        badge: 'required',
        content: (
            <>
                <CalloutBox type="fyi" title="Version requirement">
                    <Markdown>The error tracking configuration requires PostHog KMP version 0.4.0 or higher.</Markdown>
                </CalloutBox>
                <Markdown>
                    Both the project setting from the previous step and `errorTracking.autoCapture` must be enabled.
                    Replace the `PostHog.setup()` call from the configuration step with the appropriate example below.
                    The optional `inAppIncludes` prefixes mark matching stack frames as in-app code on Android, iOS, and
                    JVM. Kotlin/JS and Kotlin/Wasm ignore `inAppIncludes`.
                </Markdown>
                <Tab.Group tabs={['Android', 'iOS, Web, and JVM']}>
                    <Tab.Panels>
                        <Tab.Panel>
                            <Markdown>
                                Keep this call inside the `Application.onCreate()` method from the Android configuration
                                example:
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'kotlin',
                                        file: 'MyApplication.kt',
                                        code: dedent`
                                            import com.posthog.kmp.ErrorTrackingConfig
                                            import com.posthog.kmp.PostHog
                                            import com.posthog.kmp.PostHogConfig
                                            import com.posthog.kmp.PostHogContext

                                            PostHog.setup(
                                                config = PostHogConfig(
                                                    apiKey = "<ph_project_token>",
                                                    host = "<ph_client_api_host>",
                                                    errorTracking = ErrorTrackingConfig(
                                                        autoCapture = true,
                                                        inAppIncludes = listOf("com.example"),
                                                    ),
                                                ),
                                                context = PostHogContext(this),
                                            )
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>
                                On iOS, web, and JVM, keep using the no-argument `PostHogContext()` from the
                                configuration example:
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'kotlin',
                                        file: 'Kotlin',
                                        code: dedent`
                                            import com.posthog.kmp.ErrorTrackingConfig
                                            import com.posthog.kmp.PostHog
                                            import com.posthog.kmp.PostHogConfig
                                            import com.posthog.kmp.PostHogContext

                                            PostHog.setup(
                                                config = PostHogConfig(
                                                    apiKey = "<ph_project_token>",
                                                    host = "<ph_client_api_host>",
                                                    errorTracking = ErrorTrackingConfig(
                                                        autoCapture = true,
                                                        inAppIncludes = listOf("com.example"),
                                                    ),
                                                ),
                                                context = PostHogContext(),
                                            )
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
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

    return [...installSteps, enableExceptionAutocaptureStep, exceptionAutocaptureStep, manualCaptureStep, verifyStep]
}

export const KMPErrorTrackingInstallation = createInstallation(getKMPErrorTrackingSteps)
