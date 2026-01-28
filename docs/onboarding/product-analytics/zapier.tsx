import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getZapierSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Connect PostHog to Zapier',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Zapier lets you connect PostHog to thousands of other apps. You can use it to send events to
                        PostHog from other services or trigger actions based on PostHog events. Go to the [PostHog
                        integration page](https://zapier.com/apps/posthog/integrations) on Zapier and click **Connect
                        PostHog**. When prompted, enter your PostHog project API key:
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
                </>
            ),
        },
        {
            title: 'Create a Zap',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create a Zap that sends events to PostHog using the "Capture Event" action. Events captured via
                        Zapier will appear in PostHog just like events from any other source.
                    </Markdown>
                    <Markdown>
                        You can use Zapier to connect CRMs, payment processors, customer support tools, and more to your
                        PostHog analytics.
                    </Markdown>
                </>
            ),
        },
    ]
}

export const ZapierInstallation = createInstallation(getZapierSteps)
