import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const SvelteInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()

    const JSEventCapture = snippets?.JSEventCapture

    return (
        <Steps>
            <Step title="Install the package" badge="required">
                <Markdown>Install the PostHog JavaScript library using your package manager:</Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'bash',
                            file: 'npm',
                            code: dedent`
                                npm install posthog-js
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'yarn',
                            code: dedent`
                                yarn add posthog-js
                            `,
                        },
                        {
                            language: 'bash',
                            file: 'pnpm',
                            code: dedent`
                                pnpm add posthog-js
                            `,
                        },
                    ]}
                />
            </Step>

            <Step title="Initialize PostHog" badge="required">
                <Markdown>
                    If you haven't created a root layout already, create a new file called `+layout.js` in your
                    `src/routes` folder. Check the environment is the browser, and initialize PostHog if so:
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'src/routes/+layout.js',
                            code: dedent`
                                import posthog from 'posthog-js'
                                import { browser } from '$app/environment';
                                import { onMount } from 'svelte';

                                export const load = async () => {
                                  if (browser) {
                                    posthog.init(
                                      '<ph_project_api_key>',
                                      {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '2025-11-30',
                                        person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users too
                                      }
                                    )
                                  }

                                  return
                                };
                            `,
                        },
                    ]}
                />
                <CalloutBox type="fyi" title="SvelteKit layout">
                    <Markdown>
                        Learn more about [SvelteKit layouts](https://kit.svelte.dev/docs/routing#layout) in the official
                        documentation.
                    </Markdown>
                </CalloutBox>
            </Step>

            <Step title="Send events">{JSEventCapture && <JSEventCapture />}</Step>
        </Steps>
    )
}
