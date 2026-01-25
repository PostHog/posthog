import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getN8nSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Add the PostHog node',
            badge: 'required',
            content: (
                <Markdown>
                    n8n is an open-source workflow automation tool. In your n8n workflow, add the [PostHog
                    node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.posthog/).
                </Markdown>
            ),
        },
        {
            title: 'Create credentials',
            badge: 'required',
            content: (
                <>
                    <Markdown>Create credentials with your PostHog project API key:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'text',
                                file: 'API Key',
                                code: dedent`
                                <ph_project_api_key>
                            `,
                            },
                        ]}
                    />
                    <Markdown>Set the PostHog host URL:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'text',
                                file: 'Host',
                                code: dedent`
                                <ph_client_api_host>
                            `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure events',
            badge: 'recommended',
            content: (
                <Markdown>
                    Configure the node to capture events, identify users, or create aliases based on your workflow
                    needs. Events from n8n will appear in PostHog just like events from any other source.
                </Markdown>
            ),
        },
    ]
}

export const N8nInstallation = createInstallation(getN8nSteps)
