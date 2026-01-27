import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getMoEngageSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Open the MoEngage integration',
            badge: 'required',
            content: (
                <Markdown>
                    MoEngage is a customer engagement platform. Follow the [MoEngage PostHog integration
                    guide](https://posthog.com/docs/libraries/moengage) to set up the connection.
                </Markdown>
            ),
        },
        {
            title: 'Enter your credentials',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Verify the connection',
            badge: 'recommended',
            content: (
                <Markdown>
                    Once configured, MoEngage will send event data to PostHog, allowing you to analyze customer
                    engagement alongside your other product analytics data.
                </Markdown>
            ),
        },
    ]
}

export const MoEngageInstallation = createInstallation(getMoEngageSteps)
