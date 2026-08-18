import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getKMPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return [
        {
            title: 'Install the dependency',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add the PostHog KMP SDK to your shared module's `commonMain` source set:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'shared/build.gradle.kts',
                                code: dedent`
                                    kotlin {
                                        sourceSets {
                                            commonMain.dependencies {
                                                implementation("com.posthog:posthog-kmp:0.+")
                                            }
                                        }
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        `0.+` resolves to the latest `0.x` release. The SDK is a pre-release, so the API can change
                        between minor versions – pin an exact version from [Maven
                        Central](https://central.sonatype.com/artifact/com.posthog/posthog-kmp) if you would rather
                        upgrade deliberately.
                    </Markdown>
                    <CalloutBox type="fyi" title="Supported targets">
                        <Markdown>
                            Session replay is captured on Android, iOS and the web. It is ignored on the JVM (desktop)
                            target.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Enable session recordings in project settings',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Go to your PostHog [Project Settings](https://us.posthog.com/settings/project-replay) and enable
                        **Record user sessions**. Session recordings will not work without this setting enabled.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure PostHog with session replay',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Pass a `SessionRecordingConfig` to `PostHogConfig` from shared code. Here are all the available
                        options:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'Kotlin',
                                code: dedent`
                                    import com.posthog.kmp.PostHog
                                    import com.posthog.kmp.PostHogConfig
                                    import com.posthog.kmp.PostHogContext
                                    import com.posthog.kmp.SessionRecordingConfig

                                    val config = PostHogConfig(
                                        apiKey = "<ph_project_token>",
                                        host = "<ph_client_api_host>",

                                        // Enable session recording. Requires enabling in your project settings as well.
                                        sessionRecording = SessionRecordingConfig(
                                            enabled = true,

                                            // Whether text input values are masked. Default is true.
                                            maskAllTextInputs = true,

                                            // Whether images are masked. Default is true.
                                            maskAllImages = true,

                                            // Whether network requests are included in the recording. Default is true.
                                            captureNetworkTelemetry = true,

                                            // Capture console and system logs (iOS and web). Default is false.
                                            captureLogs = false,

                                            // Whether replays are created using high quality screenshots instead of
                                            // wireframes (experimental, Android and iOS). Default is false.
                                            // Screenshots may contain sensitive information, so use with caution.
                                            screenshot = false,

                                            // Capture Android logcat output (Android only). Default is true.
                                            captureLogcat = true,

                                            // Touch event debounce delay in milliseconds (Android only). Default is 1000.
                                            debouncerDelayMs = 1000L,
                                        ),
                                    )
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Pass that config to `PostHog.setup()`. Android needs the `Application` instance, so it takes
                        `PostHogContext(application)` – every other target takes the no-argument `PostHogContext()`.
                    </Markdown>
                    <Tab.Group tabs={['Android', 'iOS and web']}>
                        <Tab.Panels>
                            <Tab.Panel>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'kotlin',
                                            file: 'MyApplication.kt',
                                            code: dedent`
                                                import android.app.Application

                                                class MyApplication : Application() {
                                                    override fun onCreate() {
                                                        super.onCreate()

                                                        PostHog.setup(config = config, context = PostHogContext(this))
                                                    }
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'kotlin',
                                            file: 'Kotlin',
                                            code: dedent`
                                                PostHog.setup(config = config, context = PostHogContext())
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                    <Markdown>
                        For more configuration options, see the [Kotlin Multiplatform session replay
                        docs](https://posthog.com/docs/libraries/kmp#session-replay).
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Watch session recordings',
            badge: 'recommended',
            content: <>{SessionReplayFinalSteps && <SessionReplayFinalSteps />}</>,
        },
    ]
}

export const KMPInstallation = createInstallation(getKMPSteps)
