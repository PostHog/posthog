import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { PersonProfiles } from './_snippets/person-profiles'

export const getNodeJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog Node.js library using your package manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                npm install posthog-node
                            `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                yarn add posthog-node
                            `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                pnpm add posthog-node
                            `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>Initialize the PostHog client with your project API key:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'Node.js',
                                code: dedent`
                                import { PostHog } from 'posthog-node'

                                const client = new PostHog(
                                    '<ph_project_api_key>',
                                    {
                                        host: '<ph_client_api_host>'
                                    }
                                )
                            `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send an event',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>Once installed, you can manually send events to test your integration:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'Node.js',
                                code: dedent`
                                client.capture({
                                    distinctId: 'distinct_id_of_the_user',
                                    event: 'event_name',
                                    properties: {
                                        property1: 'value',
                                        property2: 'value',
                                    },
                                })
                            `,
                            },
                        ]}
                    />
                    <PersonProfiles language="javascript" file="Node.js" />
                </>
            ),
        },
    ]
}

export const NodeJSInstallation = createInstallation(getNodeJSSteps)
