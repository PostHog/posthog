import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from './js-web'

export const getPHPSteps = (
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
                            Install the PostHog PHP SDK using Composer:
                        `}
                    </Markdown>
                    <CodeBlock
                        language="bash"
                        code={dedent`
                            composer require posthog/posthog-php
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
                        language="php"
                        code={dedent`
                            require __DIR__ . '/vendor/autoload.php';
                            use PostHog\PostHog;

                            PostHog::init("<ph_project_api_key>",
                                array(
                                    'host' => '<ph_client_api_host>'
                                )
                            );
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
                    {BooleanFlag && <BooleanFlag language="php" />}
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
                    {MultivariateFlag && <MultivariateFlag language="php" />}
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
                                    language="php"
                                    code={dedent`
                                        PostHog::capture(array(
                                            'distinctId' => 'distinct_id_of_your_user',
                                            'event' => 'event_name',
                                            'send_feature_flags' => true
                                        ));
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
                                    language="php"
                                    code={dedent`
                                        PostHog::capture(array(
                                            'distinctId' => 'distinct_id_of_your_user',
                                            'event' => 'event_name',
                                            'properties' => array(
                                                '$feature/feature-flag-key' => 'variant-key' // replace feature-flag-key with your flag key. Replace 'variant-key' with the key of your variant
                                            )
                                        ));
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
            content: <>{OverrideProperties && <OverrideProperties language="php" />}</>,
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

export const PHPInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets, Tab } = useMDXComponents()

    const steps = getPHPSteps(CodeBlock, Markdown, dedent, snippets, Tab)

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
