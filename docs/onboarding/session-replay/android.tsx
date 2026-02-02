import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

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
                                    class SampleApp : Application() {

                                        companion object {
                                            const val POSTHOG_API_KEY = "<ph_project_api_key>"
                                            const val POSTHOG_HOST = "<ph_client_api_host>"
                                        }

                                        override fun onCreate() {
                                            super.onCreate()

                                            val config = PostHogAndroidConfig(
                                                apiKey = POSTHOG_API_KEY,
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
                                            config.sessionReplayConfig.captureLogcat = true

                                            // Whether replays are created using high quality screenshots. Default is false.
                                            // If disabled, replays are created using wireframes instead.
                                            // The screenshot may contain sensitive information, so use with caution
                                            config.sessionReplayConfig.screenshot = false

                                            // Throttle delay used to reduce the number of snapshots captured. Default is 1000ms
                                            config.sessionReplayConfig.throttleDelayMs = 1000

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
