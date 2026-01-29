import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getSvelteSteps as getSvelteStepsPA } from '../product-analytics/svelte'
import { StepDefinition } from '../steps'

export const getSvelteSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet

    // Get installation steps from product-analytics
    const installationSteps = getSvelteStepsPA(ctx)

    // Add flag implementation steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Client-side rendering',
            badge: 'required',
            content: (
                <>
                    <Markdown>**Basic flag implementation**</Markdown>
                    {BooleanFlag && <BooleanFlag language="javascript" />}
                    <Markdown>**Multivariate flags**</Markdown>
                    {MultivariateFlag && <MultivariateFlag language="javascript" />}
                </>
            ),
        },
        {
            title: 'Server-side rendering',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Use `posthog-node` to evaluate feature flags on the server. Initialize PostHog in your server
                        load function:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'src/routes/+page.server.js',
                                code: dedent`
                                    import { PostHog } from 'posthog-node'

                                    const posthog = new PostHog('<ph_project_api_key>', {
                                        host: '<ph_client_api_host>'
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

export const SvelteInstallation = createInstallation(getSvelteSteps)
