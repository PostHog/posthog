import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getAndroidSteps } from '../product-analytics/android'
import { StepDefinition } from '../steps'

function getSurveysAndroidSteps(ctx: OnboardingComponentsContext): StepDefinition[] {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const SurveysFinalSteps = snippets?.SurveysFinalSteps

    const installationSteps = getAndroidSteps(ctx)

    const surveysSteps: StepDefinition[] = [
        {
            title: 'Add the surveys UI module',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Add the optional \`posthog-android-surveys-compose\` module alongside the core SDK. It
                            provides a ready-made [Jetpack Compose](https://developer.android.com/jetpack/compose) UI.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'build.gradle',
                                code: dedent`
                                    dependencies {
                                        // ... existing dependencies
                                        implementation("com.posthog:posthog-android-surveys-compose:0.+")
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Enable surveys in your configuration',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Enable surveys in your PostHog configuration. The SDK auto-discovers the UI module from the
                            classpath, so matching surveys render automatically with no extra wiring.
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'SampleApp.kt',
                                code: dedent`
                                    val config = PostHogAndroidConfig(
                                        apiKey = POSTHOG_PROJECT_TOKEN,
                                        host = POSTHOG_HOST
                                    ).apply {
                                        surveys = true
                                    }

                                    PostHogAndroid.setup(appContext, config)
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]

    return [
        ...installationSteps,
        ...surveysSteps,
        {
            title: 'Next steps',
            badge: 'recommended',
            content: <>{SurveysFinalSteps && <SurveysFinalSteps />}</>,
        },
    ]
}

export const SurveysAndroidInstallation = createInstallation(getSurveysAndroidSteps)
