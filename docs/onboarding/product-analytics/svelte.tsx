import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getSvelteSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    dedent: any,
    snippets: any
): StepDefinition[] => {
    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
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
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
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
                                            defaults: '2025-11-30'
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
                </>
            ),
        },
        {
            title: 'Server-side setup',
            badge: 'optional',
            content: (
                <>
                    <Markdown>Install `posthog-node` using your package manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-node --save
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-node
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-node
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'Bun',
                                code: dedent`
                                    bun add posthog-node
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Then, initialize the PostHog Node client where you'd like to use it on the server side. For example, in a load function:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'routes/+page.server.js',
                                code: dedent`
                                    import { PostHog } from 'posthog-node';

                                    export async function load() {
                                      const posthog = new PostHog('<ph_project_api_key>', { host: '<ph_client_api_host>' });

                                      posthog.capture({
                                        distinctId: 'distinct_id_of_the_user',
                                        event: 'event_name',
                                      })

                                      await posthog.shutdown()
                                    }
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="Note">
                        <Markdown>
                            Make sure to always call `posthog.shutdown()` after capturing events from the server-side. PostHog queues events into larger batches, and this call forces all batched events to be flushed immediately.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Send events',
            badge: undefined,
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const SvelteInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()
    const steps = getSvelteSteps(CodeBlock, Markdown, CalloutBox, dedent, snippets)

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}
