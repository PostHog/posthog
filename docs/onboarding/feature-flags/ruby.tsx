import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const RubyInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets, Tab } = useMDXComponents()

    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const OverrideProperties = snippets?.OverridePropertiesSnippet

    return (
        <Steps>
            <Step title="Install PostHog" badge="required">
                <Markdown>
                    {dedent`
                        Install the PostHog Ruby SDK:
                    `}
                </Markdown>
                <CodeBlock
                    language="bash"
                    code={dedent`
                        gem install posthog-ruby
                    `}
                />
            </Step>

            <Step title="Initialize PostHog" badge="required">
                <Markdown>
                    {dedent`
                        Initialize PostHog with your project API key and host from [your project settings](https://app.posthog.com/settings/project):
                    `}
                </Markdown>
                <CodeBlock
                    language="ruby"
                    code={dedent`
                        require 'posthog-ruby'

                        posthog = PostHog::Client.new(
                            api_key: '<ph_project_api_key>',
                            host: '<ph_client_api_host>'
                        )
                    `}
                />
            </Step>

            <Step title="Evaluate boolean feature flags" badge="required">
                <Markdown>
                    {dedent`
                        Check if a feature flag is enabled:
                    `}
                </Markdown>
                {BooleanFlag && <BooleanFlag language="ruby" />}
            </Step>

            <Step title="Evaluate multivariate feature flags" badge="optional">
                <Markdown>
                    {dedent`
                        For multivariate flags, check which variant the user has been assigned:
                    `}
                </Markdown>
                {MultivariateFlag && <MultivariateFlag language="ruby" />}
            </Step>

            <Step title="Include feature flag information in events" badge="required">
                <Markdown>
                    {dedent`
                        If you want to use your feature flag to breakdown or filter events in your insights, you'll need to include feature flag information in those events. This ensures that the feature flag value is attributed correctly to the event.

                        **Note:** This step is only required for events captured using our server-side SDKs or API.
                    `}
                </Markdown>
                <Tab.Group tabs={['Set send_feature_flags (recommended)', 'Include $feature property']}>
                    <Tab.List>
                        <Tab>Set send_feature_flags (recommended)</Tab>
                        <Tab>Include $feature property</Tab>
                    </Tab.List>
                    <Tab.Panels>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    Set \`send_feature_flags\` to \`true\` in your capture call:
                                `}
                            </Markdown>
                            <CodeBlock
                                language="ruby"
                                code={dedent`
                                    posthog.capture({
                                        distinct_id: 'distinct_id_of_your_user',
                                        event: 'event_name',
                                        send_feature_flags: true,
                                    })
                                `}
                            />
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    Include the \`$feature/feature_flag_name\` property in your event properties:
                                `}
                            </Markdown>
                            <CodeBlock
                                language="ruby"
                                code={dedent`
                                    posthog.capture({
                                        distinct_id: 'distinct_id_of_your_user',
                                        event: 'event_name',
                                        properties: {
                                            '$feature/feature-flag-key': 'variant-key', # replace feature-flag-key with your flag key. Replace 'variant-key' with the key of your variant
                                        }
                                    })
                                `}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
            </Step>

            <Step title="Override server properties" badge="optional">
                {OverrideProperties && <OverrideProperties language="ruby" />}
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


