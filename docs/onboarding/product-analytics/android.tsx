import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const AndroidInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install the dependency" badge="required">
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
            </Step>

            <Step title="Configure PostHog" badge="required">
                <Markdown>Initialize PostHog in your Application class:</Markdown>
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

                                        // Create a PostHog Config with the given API key and host
                                        val config = PostHogAndroidConfig(
                                            apiKey = POSTHOG_API_KEY,
                                            host = POSTHOG_HOST
                                        )

                                        // Setup PostHog with the given Context and Config
                                        PostHogAndroid.setup(this, config)
                                    }
                                }
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Send events">
                <Markdown>Capture custom events using the PostHog SDK:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                                import com.posthog.PostHog

                                PostHog.capture(
                                    event = "button_clicked",
                                    properties = mapOf(
                                        "button_name" to "signup"
                                    )
                                )
                            `,
                        },
                    ]}
                />
                <PersonProfiles language="kotlin" />
            </Step>
        </Steps>
    )
}
