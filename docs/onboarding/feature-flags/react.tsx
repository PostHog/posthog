import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ReactInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets, Tab } = useMDXComponents()

    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const FlagPayload = snippets?.FlagPayloadSnippet

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
                        Initialize PostHog at the root of your app (such as \`main.tsx\` or \`App.tsx\`):
                    `}
                </Markdown>
                <CodeBlock
                    language="jsx"
                    code={dedent`
                        import { PostHogProvider } from 'posthog-js/react'

                        function App() {
                            return (
                                <PostHogProvider
                                    apiKey="<ph_project_api_key>"
                                    options={{
                                        api_host: '<ph_client_api_host>'
                                    }}
                                >
                                    {/* Your app */}
                                </PostHogProvider>
                            )
                        }
                    `}
                />
            </Step>

            <Step title="Use feature flags" badge="required">
                <Tab.Group tabs={['Using hooks', 'Using PostHogFeature component']}>
                    <Tab.List>
                        <Tab>Using hooks</Tab>
                        <Tab>Using PostHogFeature component</Tab>
                    </Tab.List>
                    <Tab.Panels>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    PostHog provides several hooks to make it easy to use feature flags in your React app. Use \`useFeatureFlagEnabled\` for boolean flags:
                                `}
                            </Markdown>
                            {BooleanFlag && <BooleanFlag language="react" />}
                            <Markdown>
                                {dedent`
                                    ### Multivariate flags

                                    For multivariate flags, use \`useFeatureFlagVariantKey\`:
                                `}
                            </Markdown>
                            {MultivariateFlag && <MultivariateFlag language="react" />}
                            <Markdown>
                                {dedent`
                                    ### Flag payloads

                                    The \`useFeatureFlagPayload\` hook does *not* send a \`$feature_flag_called\` event, which is required for experiments. Always use it with \`useFeatureFlagEnabled\` or \`useFeatureFlagVariantKey\`:
                                `}
                            </Markdown>
                            {FlagPayload && <FlagPayload language="react" />}
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    The \`PostHogFeature\` component simplifies code by handling feature flag related logic:
                                `}
                            </Markdown>
                            <CodeBlock
                                language="jsx"
                                code={dedent`
                                    import { PostHogFeature } from '@posthog/react'

                                    function App() {
                                        return (
                                            <PostHogFeature flag='show-welcome-message' match={true}>
                                                <div>
                                                    <h1>Hello</h1>
                                                    <p>Thanks for trying out our feature flags.</p>
                                                </div>
                                            </PostHogFeature>
                                        )
                                    }
                                `}
                            />
                            <Markdown>
                                {dedent`
                                    The \`match\` prop can be either \`true\`, or the variant key, to match on a specific variant. If you also want to show a default message, you can pass these in the \`fallback\` prop.

                                    If your flag has a payload, you can pass a function to children whose first argument is the payload:
                                `}
                            </Markdown>
                            <CodeBlock
                                language="jsx"
                                code={dedent`
                                    <PostHogFeature flag='show-welcome-message' match={true}>
                                        {(payload) => {
                                            return (
                                                <div>
                                                    <h1>{payload.welcomeMessage}</h1>
                                                    <p>Thanks for trying out our feature flags.</p>
                                                </div>
                                            )
                                        }}
                                    </PostHogFeature>
                                `}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
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


