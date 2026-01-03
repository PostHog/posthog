import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const JSWebInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()

    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const FlagPayload = snippets?.FlagPayloadSnippet
    const OnFeatureFlagsCallback = snippets?.OnFeatureFlagsCallbackSnippet
    const ReloadFlags = snippets?.ReloadFlagsSnippet

    return (
        <Steps>
            <Step title="Install PostHog" badge="required">
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
            </Step>

            <Step title="Initialize PostHog" badge="required">
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
            </Step>

            <Step title="Use boolean feature flags" badge="required">
                <Markdown>
                    {dedent`
                        Check if a feature flag is enabled:
                    `}
                </Markdown>
                {BooleanFlag && <BooleanFlag language="javascript" />}
            </Step>

            <Step title="Use multivariate feature flags" badge="optional">
                <Markdown>
                    {dedent`
                        For multivariate flags, check which variant the user has been assigned:
                    `}
                </Markdown>
                {MultivariateFlag && <MultivariateFlag language="javascript" />}
            </Step>

            <Step title="Use feature flag payloads" badge="optional">
                <Markdown>
                    {dedent`
                        Feature flags can include payloads with additional data. Fetch the payload like this:
                    `}
                </Markdown>
                {FlagPayload && <FlagPayload language="javascript" />}
            </Step>

            <Step title="Ensure flags are loaded" badge="optional">
                {OnFeatureFlagsCallback && <OnFeatureFlagsCallback />}
            </Step>

            <Step title="Reload feature flags" badge="optional">
                <Markdown>
                    {dedent`
                        Feature flag values are cached. If something has changed with your user and you'd like to refetch their flag values:
                    `}
                </Markdown>
                {ReloadFlags && <ReloadFlags language="javascript" />}
            </Step>

            <Step title="Running experiments" badge="optional">
                <Markdown>
                    {dedent`
                        Experiments run on top of our feature flags. Once you've implemented the flag in your code, you run an experiment by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            </Step>
        </Steps>
    )
}


