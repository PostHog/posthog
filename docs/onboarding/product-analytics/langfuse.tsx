import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getLangfuseSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Add Langfuse Tracing',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Langfuse supports most popular LLM models and you can bring your Langfuse data into PostHog for
                        analysis.
                    </Markdown>
                    <Markdown>
                        {`1. First add [Langfuse Tracing](https://langfuse.com/docs/tracing) to your LLM app.
2. In your [Langfuse dashboard](https://cloud.langfuse.com/), click on **Settings** and scroll down to the **Integrations** section to find the PostHog integration.`}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Configure the integration',
            badge: 'required',
            content: (
                <>
                    <Markdown>Click **Configure** and paste in your PostHog project API key:</Markdown>
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
                    <Markdown>Click **Enable** and then **Save**.</Markdown>
                    <CalloutBox type="fyi" title="Data sync timing">
                        <Markdown>
                            Langfuse batch exports your data into PostHog once a day, so it can take up to 24 hours for
                            your Langfuse data to appear in PostHog.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
    ]
}

export const LangfuseInstallation = createInstallation(getLangfuseSteps)
