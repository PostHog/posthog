import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { ReactNode } from 'react'
import { StepDefinition } from './js-web'

export const getNodeJSSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    snippets: any,
    Tab: any
): StepDefinition[] => {
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const OverrideProperties = snippets?.OverridePropertiesSnippet

    return [
        {
            title: 'Install PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Install the PostHog Node.js SDK:
                        `}
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            npm install posthog-node
                        `}
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
                            import { PostHog } from 'posthog-node'

                            const client = new PostHog('<ph_project_api_key>', {
                                host: '<ph_client_api_host>'
                            })
                        `}
                    />
                </>
            ),
        },
        {
            title: 'Evaluate boolean feature flags',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Check if a feature flag is enabled:
                        `}
                    </Markdown>
                    {BooleanFlag && <BooleanFlag language="node.js" />}
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
                    {MultivariateFlag && <MultivariateFlag language="node.js" />}
                </>
            ),
        },
        {
            title: 'Include feature flag information in events',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            If you want to use your feature flag to breakdown or filter events in your insights, you'll need to include feature flag information in those events. This ensures that the feature flag value is attributed correctly to the event.

                            **Note:** This step is only required for events captured using our server-side SDKs or API.
                        `}
                    </Markdown>
                    <Tab.Group tabs={['Set sendFeatureFlags (recommended)', 'Include $feature property']}>
                        <Tab.List>
                            <Tab>Set sendFeatureFlags (recommended)</Tab>
                            <Tab>Include $feature property</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        Set \`sendFeatureFlags\` to \`true\` in your capture call:
                                    `}
                                </Markdown>
                                <CodeBlock
                                    language="javascript"
                                    code={dedent`
                                        client.capture({
                                            distinctId: 'distinct_id_of_your_user',
                                            event: 'event_name',
                                            sendFeatureFlags: true,
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
                                    language="javascript"
                                    code={dedent`
                                        client.capture({
                                            distinctId: 'distinct_id_of_your_user',
                                            event: 'event_name',
                                            properties: {
                                                '$feature/feature-flag-key': 'variant-key' // replace feature-flag-key with your flag key. Replace 'variant-key' with the key of your variant
                                            },
                                        })
                                    `}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
        {
            title: 'Override server properties',
            badge: 'optional',
            content: <>{OverrideProperties && <OverrideProperties language="node.js" />}</>,
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

export const NodeJSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets, Tab } = useMDXComponents()

    const steps = getNodeJSSteps(CodeBlock, Markdown, dedent, snippets, Tab)

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
