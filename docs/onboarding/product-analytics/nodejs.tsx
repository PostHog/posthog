import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { PersonProfiles } from './_snippets/person-profiles'
import { StepDefinition } from '../steps'

export const getNodeJSSteps = (CodeBlock: any, Markdown: any, dedent: any): StepDefinition[] => {
    return [
        {
            title: 'Install',
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
            title: 'Configure',
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
                    <Markdown>
                        Once installed, you can manually send events to test your integration:
                    </Markdown>
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

export const NodeJSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()
    const steps = getNodeJSSteps(CodeBlock, Markdown, dedent)

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
