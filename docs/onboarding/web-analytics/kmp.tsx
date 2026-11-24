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
                        Screen views are captured automatically – screen views on Android and iOS, pageviews on the web
                        (not on JVM or macOS). A Compose Multiplatform app usually has one activity or view controller,
                        so capture each Compose screen yourself from shared code:
                    </Markdown>
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
                    <Markdown>
                        To send only the screen views you capture yourself, set `captureScreenViews = false` in your
                        `PostHogConfig`.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const KMPInstallation = createInstallation(getKMPSteps)
