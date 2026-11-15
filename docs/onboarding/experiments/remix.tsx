import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getRemixInstallSteps } from '../product-analytics/remix'
import { StepDefinition } from '../steps'

export const getRemixSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { Markdown, Tab, dedent, snippets } = ctx
    const ExperimentImplementation = snippets?.ExperimentImplementationSnippet

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
                                        For client-side experiments, use \`posthog-js\`:
                                    `}
                                </Markdown>
                                {ExperimentImplementation && <ExperimentImplementation language="javascript" />}
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        For server-side experiments, install and use \`posthog-node\`:
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

    return [...getRemixInstallSteps(ctx), ...experimentSteps]
}

export const RemixInstallation = createInstallation(getRemixSteps)
