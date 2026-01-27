import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getRemixSteps as getRemixStepsPA } from '../product-analytics/remix'
import { StepDefinition } from '../steps'

export const getRemixSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    // Get installation steps from product-analytics
    const installationSteps = getRemixStepsPA(ctx)

    // Add flag implementation steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Client-side rendering',
            badge: 'required',
            content: (
                <>
                    <Markdown>**Basic flag implementation**</Markdown>
                    {BooleanFlag && <BooleanFlag language="typescript" />}
                    <Markdown>**Multivariate flags**</Markdown>
                    {MultivariateFlag && <MultivariateFlag language="typescript" />}
                </>
            ),
        },
        {
            title: 'Server-side rendering',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use `posthog-node` to evaluate feature flags on the server. Initialize PostHog in your API
                        route or loader:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'app/api/example/route.ts',
                                code: dedent`
                                    import { PostHog } from 'posthog-node'

                                    const posthog = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
                                        host: process.env.NEXT_PUBLIC_POSTHOG_HOST
                                    })
                                `,
                            },
                        ]}
                    />
                    <Markdown>**Basic flag implementation**</Markdown>
                    {BooleanFlag && <BooleanFlag language="node.js" />}
                    <Markdown>**Multivariate flags**</Markdown>
                    {MultivariateFlag && <MultivariateFlag language="node.js" />}
                </>
            ),
        },
        {
            title: 'Running experiments',
            badge: 'optional',
            content: (
                <Markdown>
                    Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run
                    an experiment by creating a new experiment in the PostHog dashboard.
                </Markdown>
            ),
        },
    ]

    return [...installationSteps, ...flagSteps]
}

export const RemixInstallation = createInstallation(getRemixSteps)
