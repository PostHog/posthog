import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { ReactNode } from 'react'

export interface StepDefinition {
    title: string
    badge?: 'required' | 'optional'
    content: ReactNode
}

export const getJSWebSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    snippets: any
): StepDefinition[] => {
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const FlagPayload = snippets?.FlagPayloadSnippet
    const OnFeatureFlagsCallback = snippets?.OnFeatureFlagsCallbackSnippet
    const ReloadFlags = snippets?.ReloadFlagsSnippet

    return [
        {
            title: 'Install PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Install PostHog using your preferred package manager:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-js
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Initialize PostHog with your project API key and host from [your project settings](https://app.posthog.com/settings/project):
                        `}
                    </Markdown>
                    <CodeBlock
                        language="javascript"
                        code={dedent`
                            import posthog from 'posthog-js'

                            posthog.init('<ph_project_api_key>', {
                                api_host: '<ph_client_api_host>'
                            })
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Use boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Check if a feature flag is enabled:
                        `}
                    </Markdown>
                    {BooleanFlag && <BooleanFlag language="javascript" />}
                </>
            ),
        },
        {
            title: 'Use multivariate feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            For multivariate flags, check which variant the user has been assigned:
                        `}
                    </Markdown>
                    {MultivariateFlag && <MultivariateFlag language="javascript" />}
                </>
            ),
        },
        {
            title: 'Use feature flag payloads',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Feature flags can include payloads with additional data. Fetch the payload like this:
                        `}
                    </Markdown>
                    {FlagPayload && <FlagPayload language="javascript" />}
                </>
            ),
        },
        {
            title: 'Ensure flags are loaded',
            badge: 'optional',
            content: <>{OnFeatureFlagsCallback && <OnFeatureFlagsCallback />}</>,
        },
        {
            title: 'Reload feature flags',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Feature flag values are cached. If something has changed with your user and you'd like to refetch their flag values:
                        `}
                    </Markdown>
                    {ReloadFlags && <ReloadFlags language="javascript" />}
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
}

export const JSWebInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()

    const steps = getJSWebSteps(CodeBlock, Markdown, dedent, snippets)

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


