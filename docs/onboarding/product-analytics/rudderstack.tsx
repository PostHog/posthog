import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const RudderstackInstallation = (): JSX.Element => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                RudderStack is an open-source customer data platform that can route your analytics data to PostHog and
                other destinations. In your RudderStack dashboard, go to **Destinations** &gt; **Add Destination** and
                search for **PostHog**.
            </Markdown>
            <Markdown>Enter your PostHog project API key:</Markdown>
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
                Connect your source to the PostHog destination. RudderStack will now forward `track`, `identify`,
                `page`, and `group` calls to PostHog.
            </Markdown>
            <CalloutBox type="fyi" title="Learn more">
                <Markdown>
                    See the [RudderStack integration docs](https://posthog.com/docs/libraries/rudderstack) for more
                    details.
                </Markdown>
            </CalloutBox>
        </>
    )
}
