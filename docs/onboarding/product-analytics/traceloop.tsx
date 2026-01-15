import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const TraceloopInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Access the integrations page" badge="required">
                <Markdown>
                    Traceloop supports most popular LLM models and you can bring your Traceloop data into PostHog for
                    analysis.
                </Markdown>
                <Markdown>
                    Go to the [integrations page](https://app.traceloop.com/settings/integrations) in your Traceloop
                    dashboard and click on the PostHog card.
                </Markdown>
            </Step>

            <Step title="Configure the integration" badge="required">
                <Markdown>Paste in your PostHog project API key:</Markdown>
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
                <Markdown>Paste in your PostHog host:</Markdown>
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
                <Markdown>Select the environment you want to connect to PostHog and click **Enable**.</Markdown>
                <Markdown>
                    Traceloop events will now be exported into PostHog as soon as they're available.
                </Markdown>
            </Step>
        </Steps>
    )
}
