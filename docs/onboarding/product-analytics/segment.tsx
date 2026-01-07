import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const SegmentInstallation = (): JSX.Element => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                {`Segment is a customer data platform that can route your analytics data to PostHog and other destinations. In your Segment workspace, go to **Connections** > **Catalog** and search for **PostHog**. Click **Add Destination** and select the source you want to connect.`}
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
                {`Segment will now forward \`track\`, \`identify\`, \`page\`, and \`group\` calls to PostHog.`}
            </Markdown>
            <CalloutBox type="fyi" title="Learn more">
                <Markdown>
                    See the [Segment integration docs](https://posthog.com/docs/libraries/segment) for more details.
                </Markdown>
            </CalloutBox>
        </>
    )
}
