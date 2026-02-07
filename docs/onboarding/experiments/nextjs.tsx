import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { getNextJSSteps as getNextJSStepsPA } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, Tab, dedent, snippets } = ctx
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

    // Get installation steps from product-analytics (not feature-flags)
    // Filter to only keep installation-related steps, not usage steps
    const installationSteps = getNextJSStepsPA(ctx).filter(
        (step: StepDefinition) =>
            step.title === 'Install the package' ||
            step.title === 'Add environment variables' ||
            step.title === 'Initialize PostHog'
    )

    // Add experiments-specific steps
    const experimentSteps: StepDefinition[] = [
        {
            title: 'Implement your experiment',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Experiments run on top of our feature flags. You can define which version of your code runs based on the return value of the feature flag:
                        `}
                    </Markdown>

                    <Tab.Group tabs={['Client-side', 'Server-side']}>
                        <Tab.List>
                            <Tab>Client-side</Tab>
                            <Tab>Server-side</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        For client-side experiments in React components, you can use the \`useFeatureFlagVariantKey\` hook or the \`PostHogFeature\` component:
                                    `}
                                </Markdown>
                                {ExperimentImplementation && <ExperimentImplementation language="react" />}
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        For server-side experiments in API routes or server actions, use \`posthog-node\`:
                                    `}
                                </Markdown>
                                {ExperimentImplementation && <ExperimentImplementation language="node.js" />}
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>
                </>
            ),
        },
        {
            title: 'Run your experiment',
            badge: 'required',
            content: (
                <Markdown>
                    {dedent`
                        Once you've implemented the feature flag in your code, you'll enable it for a target audience by creating a new experiment in the PostHog dashboard.
                    `}
                </Markdown>
            ),
        },
    ]

    return [...installationSteps, ...experimentSteps]
}

export const NextJSInstallation = createInstallation(getNextJSSteps)
