import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getAndroidSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
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
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Once installed, PostHog will automatically start capturing events. You can also manually send
                        events to test your integration:
                    </Markdown>
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
                </>
            ),
        },
    ]
}

export const AndroidInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getAndroidSteps(CodeBlock, Markdown, dedent)

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}
