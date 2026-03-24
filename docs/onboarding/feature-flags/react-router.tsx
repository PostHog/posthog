import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getReactRouterSteps as getReactRouterStepsPA } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    const installationSteps = getReactRouterStepsPA(ctx)
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
                        Use `posthog-node` to evaluate feature flags on the server. You can access PostHog in a React
                        Router loader:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'app/routes/example.tsx',
                                code: dedent`
                                    import { PostHog } from 'posthog-node'
                                    import type { Route } from './+types/example'

                                    export async function loader({ request }: Route.LoaderArgs) {
                                        const posthog = new PostHog(process.env.VITE_PUBLIC_POSTHOG_TOKEN!, {
                                            host: process.env.VITE_PUBLIC_POSTHOG_HOST
                                        })

                                        try {
                                            // use posthog for feature flags here
                                        } finally {
                                            await posthog.shutdown()
                                        }
                                    }
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

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
