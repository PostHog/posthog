import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNextJSSteps as getNextJSStepsPA } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    // Get installation steps from product-analytics
    const installationSteps = getNextJSStepsPA(ctx)

    // Add flag implementation steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Client-side rendering',
            badge: 'required' as const,
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
            badge: 'required' as const,
            content: (
                <>
                    <Markdown>
                        Use `posthog-node` to evaluate feature flags on the server. The server-side SDK uses an async
                        API and requires a `distinct_id` for each user. Initialize PostHog in your API route or server
                        action:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'app/api/example/route.ts',
                                code: dedent`
                                    import { PostHog } from 'posthog-node'

                                    const client = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
                                        host: process.env.NEXT_PUBLIC_POSTHOG_HOST
                                    })
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Then use the client to check flags. Note that server-side flag evaluation is async and requires
                        a `distinct_id`:
                    </Markdown>
                    <Markdown>**Basic flag implementation**</Markdown>
                    {BooleanFlag && <BooleanFlag language="node.js" />}
                    <Markdown>**Multivariate flags**</Markdown>
                    {MultivariateFlag && <MultivariateFlag language="node.js" />}
                </>
            ),
        },
        {
            title: 'Running experiments',
            badge: 'optional' as const,
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

export const NextJSInstallation = createInstallation(getNextJSSteps)
