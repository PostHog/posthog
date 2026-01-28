import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getTraceloopSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Access the integrations page',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Traceloop supports most popular LLM models and you can bring your Traceloop data into PostHog
                        for analysis.
                    </Markdown>
                    <Markdown>
                        Go to the [integrations page](https://app.traceloop.com/settings/integrations) in your Traceloop
                        dashboard and click on the PostHog card.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure the integration',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
    ]
}

export const TraceloopInstallation = createInstallation(getTraceloopSteps)
