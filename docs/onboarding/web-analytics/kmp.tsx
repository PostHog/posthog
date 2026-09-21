import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getKMPInstallSteps } from '../product-analytics/kmp'
import { StepDefinition } from '../steps'

export const getKMPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, CodeBlock, dedent, snippets } = ctx
    const MobileFinalSteps = snippets?.MobileFinalSteps

    return [
        ...getKMPInstallSteps(ctx),
        {
            title: 'Track screen views',
            badge: 'recommended' as const,
            content: (
                <>
                    {MobileFinalSteps && <MobileFinalSteps />}
                    <Markdown>
                        Screen views are off by default. Set `captureScreenViews = true` to capture them automatically –
                        screen views on Android and iOS, pageviews on the web:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'Kotlin',
                                code: dedent`
                                    PostHogConfig(
                                        apiKey = "<ph_project_token>",
                                        host = "<ph_client_api_host>",
                                        captureScreenViews = true,
                                    )
                                `,
                            },
                        ]}
                    />
                    <Markdown>You can also capture a screen view yourself from shared code:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'Kotlin',
                                code: dedent`
                                    import com.posthog.kmp.PostHog

                                    PostHog.screen(
                                        screenName = "Dashboard",
                                        properties = mapOf(
                                            "background" to "blue"
                                        )
                                    )
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const KMPInstallation = createInstallation(getKMPSteps)
