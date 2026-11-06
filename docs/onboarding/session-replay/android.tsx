import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getAndroidSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent, snippets } = ctx
    const SessionReplayFinalSteps = snippets?.SessionReplayFinalSteps

    return [
        {
            title: 'Install the dependency',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add the PostHog Android SDK to your `build.gradle` dependencies:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'build.gradle',
                                code: dedent`
                                    dependencies {
                                        implementation("com.posthog:posthog-android:3.+")
                                    }
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="SDK version">
                        <Markdown>
                            Session replay requires PostHog Android SDK version 3.4.0 or higher. We recommend always
                            using the latest version.
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
                        Add `sessionReplay = true` to your PostHog configuration. Here are all the available options:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'SampleApp.kt',
                                code: dedent`
                                    import com.posthog.android.replay.PostHogScreenshotColorMode

                                    class SampleApp : Application() {

                                        companion object {
                                            const val POSTHOG_TOKEN = "<ph_project_token>"
                                            const val POSTHOG_HOST = "<ph_client_api_host>"
                                        }

                                        override fun onCreate() {
                                            super.onCreate()

                                            val config = PostHogAndroidConfig(
                                                apiKey = POSTHOG_TOKEN,
                                                host = POSTHOG_HOST
                                            )

                                            // Enable session recording. Requires enabling in your project settings as well.
                                            // Default is false.
                                            config.sessionReplay = true

                                            // Whether text and text input fields are masked. Default is true.
                                            // Password inputs are always masked regardless
                                            config.sessionReplayConfig.maskAllTextInputs = true

                                            // Whether images are masked. Default is true.
                                            config.sessionReplayConfig.maskAllImages = true

                                            // Capture logs automatically. Default is true.
                                            // 
                                            // Support for remote configuration 
                                            // in the [session replay settings](https://app.posthog.com/settings/project-replay#replay-log-capture)
                                            // requires SDK version 3.32.0 or higher.
                                            config.sessionReplayConfig.captureLogcat = true

                                            // Whether replays are created using high quality screenshots. Default is false.
                                            // If disabled, replays are created using wireframes instead.
                                            // The screenshot may contain sensitive information, so use with caution
                                            config.sessionReplayConfig.screenshot = false

                                            // Experimental screenshot settings require SDK 3.63.0+ and screenshot = true.
                                            // We recommend the values below to balance performance and image quality.
                                            // Lower resolution and RGB_565 reduce capture time and memory use.

                                            // Scale each screenshot dimension from 0.1 to 1.0. Default is 1.0.
                                            config.sessionReplayConfig.screenshotScale = 0.5f

                                            // RGB_565 uses two bytes per pixel instead of four, with lower color precision
                                            // and no transparency. Transparent window regions appear black. Default is ARGB_8888.
                                            config.sessionReplayConfig.screenshotColorMode = PostHogScreenshotColorMode.RGB_565

                                            // WebP compression quality from 0 to 100. Default is 30.
                                            config.sessionReplayConfig.screenshotCompressionQuality = 30

                                            // Throttle delay used to reduce the number of snapshots captured. Default is 1000ms
                                            config.sessionReplayConfig.throttleDelayMs = 1000

                                            // Sample rate for session recordings. A value between 0.0 and 1.0.
                                            // 1.0 means 100% of sessions will be recorded. 0.5 means 50%, and so on.
                                            // Default is null (all sessions are recorded).
                                            // 
                                            // Support for remote configuration
                                            // in the [session replay triggers](https://us.posthog.com/settings/project-replay#replay-triggers)
                                            // requires SDK version 3.34.0 or higher.
                                            config.sessionReplayConfig.sampleRate = null

                                            PostHogAndroid.setup(this, config)
                                        }
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        For more configuration options, see the [Android session replay
                        docs](https://posthog.com/docs/session-replay/installation?tab=Android).
                    </Markdown>
                    <CalloutBox type="fyi" title="Requirements">
                        <Markdown>
                            Requires Android API 26 or higher. Jetpack Compose is only supported if `screenshot` is
                            enabled.
                        </Markdown>
                    </CalloutBox>
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

export const AndroidInstallation = createInstallation(getAndroidSteps)
