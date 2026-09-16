import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getKMPInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Tab, dedent } = ctx

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
                        upgrade deliberately. Kotlin/Wasm support requires `0.2.0` or higher.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Call `PostHog.setup()` once, early in your app's lifecycle. The config is shared across every
                        target – only the `PostHogContext` differs per platform.
                    </Markdown>
                    <Tab.Group tabs={['Android', 'iOS', 'Web', 'JVM']}>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    Android needs the `Application` instance, so set PostHog up from your `Application`
                                    class – not from an Activity, whose `onCreate` re-runs on every recreation (for
                                    example, on rotation):
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'kotlin',
                                            file: 'MyApplication.kt',
                                            code: dedent`
                                                import android.app.Application
                                                import com.posthog.kmp.PostHog
                                                import com.posthog.kmp.PostHogConfig
                                                import com.posthog.kmp.PostHogContext

                                                class MyApplication : Application() {
                                                    override fun onCreate() {
                                                        super.onCreate()

                                                        PostHog.setup(
                                                            config = PostHogConfig(
                                                                apiKey = "<ph_project_token>",
                                                                host = "<ph_client_api_host>",
                                                            ),
                                                            context = PostHogContext(this),
                                                        )
                                                    }
                                                }
                                            `,
                                        },
                                    ]}
                                />
                                <Markdown>Register the class in your `AndroidManifest.xml`:</Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'xml',
                                            file: 'android/src/main/AndroidManifest.xml',
                                            code: dedent`
                                                <application android:name=".MyApplication" ...>
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>On iOS, use the no-argument `PostHogContext()`:</Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'kotlin',
                                            file: 'MainViewController.kt',
                                            code: dedent`
                                                import com.posthog.kmp.PostHog
                                                import com.posthog.kmp.PostHogConfig
                                                import com.posthog.kmp.PostHogContext

                                                fun MainViewController() = ComposeUIViewController {
                                                    LaunchedEffect(Unit) {
                                                        PostHog.setup(
                                                            config = PostHogConfig(
                                                                apiKey = "<ph_project_token>",
                                                                host = "<ph_client_api_host>",
                                                            ),
                                                            context = PostHogContext(),
                                                        )
                                                    }
                                                    App()
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    On the web (Kotlin/JS and Kotlin/Wasm), use the no-argument `PostHogContext()`:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'kotlin',
                                            file: 'main.kt',
                                            code: dedent`
                                                import com.posthog.kmp.PostHog
                                                import com.posthog.kmp.PostHogConfig
                                                import com.posthog.kmp.PostHogContext

                                                fun main() {
                                                    PostHog.setup(
                                                        config = PostHogConfig(
                                                            apiKey = "<ph_project_token>",
                                                            host = "<ph_client_api_host>",
                                                        ),
                                                        context = PostHogContext(),
                                                    )
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    On the JVM – for example, a Compose Multiplatform desktop app – use the no-argument
                                    `PostHogContext()`:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'kotlin',
                                            file: 'main.kt',
                                            code: dedent`
                                                import com.posthog.kmp.PostHog
                                                import com.posthog.kmp.PostHogConfig
                                                import com.posthog.kmp.PostHogContext

                                                fun main() = application {
                                                    PostHog.setup(
                                                        config = PostHogConfig(
                                                            apiKey = "<ph_project_token>",
                                                            host = "<ph_client_api_host>",
                                                        ),
                                                        context = PostHogContext(),
                                                    )
                                                    // ...
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
    ]
}

export const getKMPEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { CodeBlock, Markdown, dedent } = ctx

    return {
        title: 'Send events',
        badge: 'recommended',
        content: (
            <>
                <Markdown>
                    Once installed, PostHog automatically captures app lifecycle events on Android and iOS. Send an
                    event manually from shared code to test your integration:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'kotlin',
                            file: 'Kotlin',
                            code: dedent`
                                    import com.posthog.kmp.PostHog

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
            </>
        ),
    }
}

export const getKMPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getKMPInstallSteps(ctx),
    getKMPEventStep(ctx),
]

export const KMPInstallation = createInstallation(getKMPSteps)
