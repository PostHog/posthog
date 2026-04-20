import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getGoSteps as getGoStepsPA } from '../product-analytics/go'
import { StepDefinition } from '../steps'

export const getGoSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, Tab, snippets } = ctx
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const OverrideProperties = snippets?.OverridePropertiesSnippet

    // Get installation steps from product-analytics
    const installationSteps = getGoStepsPA(ctx)

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
                    {BooleanFlag && <BooleanFlag language="go" />}
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
                    {MultivariateFlag && <MultivariateFlag language="go" />}
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
                    <Tab.Group tabs={['Set SendFeatureFlags (recommended)', 'Include $feature property']}>
                        <Tab.List>
                            <Tab>Set SendFeatureFlags (recommended)</Tab>
                            <Tab>Include $feature property</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        Set \`SendFeatureFlags\` to \`true\` in your capture call:
                                    `}
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'go',
                                            file: 'Go',
                                            code: dedent`
                                                client.Enqueue(posthog.Capture{
                                                    DistinctId: "distinct_id_of_your_user",
                                                    Event:      "event_name",
                                                    SendFeatureFlags: true,
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
                                            language: 'go',
                                            file: 'Go',
                                            code: dedent`
                                                client.Enqueue(posthog.Capture{
                                                    DistinctId: "distinct_id_of_your_user",
                                                    Event:      "event_name",
                                                    Properties: posthog.NewProperties().
                                                        Set("$feature/feature-flag-key", "variant-key"), // replace feature-flag-key with your flag key. Replace 'variant-key' with the key of your variant
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
            content: <>{OverrideProperties && <OverrideProperties language="go" />}</>,
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

export const GoInstallation = createInstallation(getGoSteps)
