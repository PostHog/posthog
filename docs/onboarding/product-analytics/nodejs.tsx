import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'

export const NodeJSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Install" badge="required">
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
            </Step>

            <Step title="Configure" badge="required">
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
            </Step>

            <Step title="Send an event">
                <Markdown>Capture events with properties:</Markdown>
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
            </Step>
        </Steps>
    )
}
