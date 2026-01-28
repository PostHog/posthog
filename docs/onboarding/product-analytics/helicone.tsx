import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getHeliconeSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Set up Helicone',
            badge: 'required',
            content: (
                <Markdown>
                    Helicone supports most popular LLM models and you can bring your Helicone data into PostHog for
                    analysis. Sign up to [Helicone](https://www.helicone.ai/) and add it to your LLM app.
                </Markdown>
            ),
        },
        {
            title: 'Add PostHog headers',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Similar to how you add a [Helicone-Auth
                        header](https://docs.helicone.ai/helicone-headers/header-directory#supported-headers) when
                        installing Helicone, add two new headers **Helicone-Posthog-Key** and **Helicone-Posthog-Host**
                        with your PostHog details:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'python',
                                file: 'Python',
                                code: dedent`
                                # Example for adding it to OpenAI in Python

                                client = OpenAI(
                                    api_key="your-api-key-here",  # Replace with your OpenAI API key
                                    base_url="https://oai.hconeai.com/v1",  # Set the API endpoint
                                    default_headers={
                                        "Helicone-Auth": f"Bearer {HELICONE_API_KEY}",
                                        "Helicone-Posthog-Key": "<ph_project_api_key>",
                                        "Helicone-Posthog-Host": "<ph_client_api_host>",
                                    }
                                )
                            `,
                            },
                        ]}
                    />
                    <Markdown>Helicone events will now be exported into PostHog as soon as they're available.</Markdown>
                </>
            ),
        },
    ]
}

export const HeliconeInstallation = createInstallation(getHeliconeSteps)
