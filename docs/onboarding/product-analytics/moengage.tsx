import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const MoEngageInstallation = (): JSX.Element => {
    const { CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                MoEngage is a customer engagement platform. Follow the [MoEngage PostHog integration
                guide](https://posthog.com/docs/libraries/moengage) to set up the connection. When prompted, enter your
                PostHog project API key:
            </Markdown>
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
            <Markdown>
                Once configured, MoEngage will send event data to PostHog, allowing you to analyze customer engagement
                alongside your other product analytics data.
            </Markdown>
        </>
    )
}
