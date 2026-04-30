import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getPythonSteps as getPythonStepsPA } from '../product-analytics/python'
import { StepDefinition } from '../steps'

export const getPythonSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, Tab, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const OverrideProperties = snippets?.OverridePropertiesSnippet

    // Get installation steps from product-analytics
    const installationSteps = getPythonStepsPA(ctx)

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
                    {BooleanFlag && <BooleanFlag language="python" />}
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
                    {MultivariateFlag && <MultivariateFlag language="python" />}
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
                    <Tab.Group tabs={['Pass evaluated flags (recommended)', 'Include $feature property']}>
                        <Tab.List>
                            <Tab>Pass evaluated flags (recommended)</Tab>
                            <Tab>Include $feature property</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        Pass the same \`flags\` snapshot that you used for branching. This attaches the exact flag values from that evaluation and doesn't make another \`/flags\` request:
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'python',
                                            file: 'Python',
                                            code: dedent`
                                                flags = posthog.evaluate_flags("distinct_id_of_the_user")

                                                posthog.capture(
                                                    "event_name",
                                                    distinct_id="distinct_id_of_the_user",
                                                    flags=flags,
                                                )
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
                                            language: 'python',
                                            file: 'Python',
                                            code: dedent`
                                                posthog.capture(
                                                    "event_name",
                                                    distinct_id="distinct_id_of_the_user",
                                                    properties={
                                                        "$feature/feature-flag-key": "variant-key"  # replace feature-flag-key with your flag key. Replace 'variant-key' with the key of your variant
                                                    },
                                                )
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
            content: <>{OverrideProperties && <OverrideProperties language="python" />}</>,
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

    return [...installationSteps, ...flagSteps]
}

export const PythonInstallation = createInstallation(getPythonSteps)
