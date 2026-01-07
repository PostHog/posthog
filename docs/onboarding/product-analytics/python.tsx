import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const PythonInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()

    const PythonEventCapture = snippets?.PythonEventCapture

    return (
        <Steps>
            <Step title="Install the package" badge="required">
                <Markdown>Install the PostHog Python library using pip:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'Terminal',
                            code: dedent`
                                pip install posthog
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Initialize PostHog" badge="required">
                <Markdown>
                    Initialize the PostHog client with your project API key and host from your project settings:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'python',
                            file: 'Python',
                            code: dedent`
                                from posthog import Posthog

                                posthog = Posthog(
                                    project_api_key='<ph_project_api_key>',
                                    host='<ph_client_api_host>'
                                )
                            `,
                        },
                    ]}
                />
                <CalloutBox type="fyi" title="Django integration">
                    <Markdown>
                        If you're using Django, check out our [Django
                        integration](https://posthog.com/docs/libraries/django) for automatic request tracking.
                    </Markdown>
                </CalloutBox>
            </Step>

            <Step title="Send events">
                {PythonEventCapture && <PythonEventCapture />}
            </Step>
        </Steps>
    )
}
