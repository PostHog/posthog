import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ZapierInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <Steps>
            <Step title="Connect PostHog to Zapier" badge="required">
                <Markdown>
                    {`Zapier lets you connect PostHog to thousands of other apps. You can use it to send events to PostHog from other services or trigger actions based on PostHog events. Go to the [PostHog integration page](https://zapier.com/apps/posthog/integrations) on Zapier and click **Connect PostHog**. When prompted, enter your PostHog project API key:`}
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
            </Step>

            <Step title="Create a Zap" badge="required">
                <Markdown>
                    Create a Zap that sends events to PostHog using the "Capture Event" action. Events captured via
                    Zapier will appear in PostHog just like events from any other source.
                </Markdown>
                <Markdown>
                    You can use Zapier to connect CRMs, payment processors, customer support tools, and more to your
                    PostHog analytics.
                </Markdown>
            </Step>
        </Steps>
    )
}
