import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const MoEngageInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Open the MoEngage integration" badge="required">
                <Markdown>
                    MoEngage is a customer engagement platform. Follow the [MoEngage PostHog integration
                    guide](https://posthog.com/docs/libraries/moengage) to set up the connection.
                </Markdown>
            </Step>

            <Step title="Enter your credentials" badge="required">
                <Markdown>When prompted, enter your PostHog project API key:</Markdown>
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
                <Markdown>Enter your PostHog host:</Markdown>
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
            </Step>

            <Step title="Verify the connection" badge="recommended">
                <Markdown>
                    Once configured, MoEngage will send event data to PostHog, allowing you to analyze customer engagement
                    alongside your other product analytics data.
                </Markdown>
            </Step>
        </Steps>
    )
}
