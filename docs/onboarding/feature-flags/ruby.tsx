import { getRubySteps as getRubyStepsPA } from '../product-analytics/ruby'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getRubySteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    Tab: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const OverrideProperties = snippets?.OverridePropertiesSnippet

    // Get installation steps from product-analytics
    const installationSteps = getRubyStepsPA(CodeBlock, Markdown, dedent)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
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
                    {BooleanFlag && <BooleanFlag language="ruby" />}
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
                    {MultivariateFlag && <MultivariateFlag language="ruby" />}
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
                                    blocks={[
                                        {
                                            language: 'ruby',
                                            file: 'Ruby',
                                            code: dedent`
                                                posthog.capture({
                                                    distinct_id: 'distinct_id_of_your_user',
                                                    event: 'event_name',
                                                    send_feature_flags: true,
                                                })
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        Include the \`$feature/feature_flag_name\` property in your event properties:
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'ruby',
                                            file: 'Ruby',
                                            code: dedent`
                                                posthog.capture({
                                                    distinct_id: 'distinct_id_of_your_user',
                                                    event: 'event_name',
                                                    properties: {
                                                        '$feature/feature-flag-key': 'variant-key', # replace feature-flag-key with your flag key. Replace 'variant-key' with the key of your variant
                                                    }
                                                })
                                            `,
                                        },
                                    ]}
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
            content: <>{OverrideProperties && <OverrideProperties language="ruby" />}</>,
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

    const allSteps = [...installationSteps, ...flagSteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const RubyInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets, Tab } = useMDXComponents()
    const steps = getRubySteps(CodeBlock, Markdown, dedent, Tab, snippets, { modifySteps })

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
