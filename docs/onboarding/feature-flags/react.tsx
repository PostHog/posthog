import { getReactSteps as getReactStepsPA } from '../product-analytics/react'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getReactSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    dedent: any,
    Tab: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const FlagPayload = snippets?.FlagPayloadSnippet

    // Get installation steps from product-analytics
    const installationSteps = getReactStepsPA(CodeBlock, Markdown, CalloutBox, dedent, snippets)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
        {
            title: 'Use feature flags',
            badge: 'required',
            content: (
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
                                blocks={[
                                    {
                                        language: 'jsx',
                                        file: 'App.tsx',
                                        code: dedent`
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
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    The \`match\` prop can be either \`true\`, or the variant key, to match on a specific variant. If you also want to show a default message, you can pass these in the \`fallback\` prop.

                                    If your flag has a payload, you can pass a function to children whose first argument is the payload:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'jsx',
                                        file: 'App.tsx',
                                        code: dedent`
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
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
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

    const allSteps = [...installationSteps, ...flagSteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const ReactInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets, Tab } = useMDXComponents()
    const steps = getReactSteps(CodeBlock, Markdown, CalloutBox, dedent, Tab, snippets, { modifySteps })

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
