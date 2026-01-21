import { getJSWebSteps as getJSWebStepsPA } from '../product-analytics/js-web'
import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition, StepModifier } from '../steps'

export const getJSWebSteps = (
    CodeBlock: any,
    Markdown: any,
    dedent: any,
    snippets: any,
    options?: StepModifier
): StepDefinition[] => {
    const BooleanFlag = snippets?.BooleanFlagSnippet
    const MultivariateFlag = snippets?.MultivariateFlagSnippet
    const FlagPayload = snippets?.FlagPayloadSnippet
    const OnFeatureFlagsCallback = snippets?.OnFeatureFlagsCallbackSnippet
    const ReloadFlags = snippets?.ReloadFlagsSnippet

    // Get installation steps from product-analytics
    const installationSteps = getJSWebStepsPA(CodeBlock, Markdown, dedent, snippets)

    // Add flag-specific steps
    const flagSteps: StepDefinition[] = [
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

    const allSteps = [...installationSteps, ...flagSteps]
    return options?.modifySteps ? options.modifySteps(allSteps) : allSteps
}

export const JSWebInstallation = ({ modifySteps }: StepModifier = {}): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getJSWebSteps(CodeBlock, Markdown, dedent, snippets, { modifySteps })

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
