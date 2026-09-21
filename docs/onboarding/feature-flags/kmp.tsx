import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getKMPSteps as getKMPStepsPA } from '../product-analytics/kmp'
import { StepDefinition } from '../steps'

export const getKMPSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    // Get installation steps from product-analytics
    const installationSteps = getKMPStepsPA(ctx)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Evaluate boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Flags are preloaded on setup, so this call is synchronous:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'Kotlin',
                                code: dedent`
                                    if (PostHog.isFeatureEnabled("flag-key")) {
                                        // Do something differently for this user
                                        // Optional: fetch the payload
                                        val payload = PostHog.getFeatureFlagResult("flag-key")?.getPayloadAs<Map<String, Any>>()
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Evaluate multivariate feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For multivariate flags, check which variant the user has been assigned:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'Kotlin',
                                code: dedent`
                                    when (PostHog.getFeatureFlag("flag-key")) {
                                        "control" -> showOriginalPricing()
                                        "variant-key" -> showNewPricing()
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Reload flags after identifying',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Flags are fetched on setup and cached. If a user's properties change – for example, after \`identify\` – reload them so they reflect the latest state:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'kotlin',
                                file: 'Kotlin',
                                code: dedent`
                                    PostHog.reloadFeatureFlags {
                                        // flags are now up to date
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Running experiments',
            badge: 'optional',
            content: (
                <Markdown>
                    {dedent`
                        Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an experiment by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]

    return [...installationSteps, ...flagSteps]
}

export const KMPInstallation = createInstallation(getKMPSteps)
