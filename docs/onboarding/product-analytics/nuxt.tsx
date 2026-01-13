import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getNuxtSteps = (
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
                    <CalloutBox type="fyi" title="Nuxt version">
                        <Markdown>
                            This guide is for Nuxt v3.0 and above. For Nuxt v2.16 and below, see our [Nuxt
                            docs](https://posthog.com/docs/libraries/nuxt-js#nuxt-v216-and-below).
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Add environment variables',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add your PostHog API key and host to your `nuxt.config.js` file:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'nuxt.config.js',
                                code: dedent`
                                    export default defineNuxtConfig({
                                      runtimeConfig: {
                                        public: {
                                          posthogPublicKey: '<ph_project_api_key>',
                                          posthogHost: '<ph_client_api_host>',
                                          posthogDefaults: '2025-11-30'
                                        }
                                      }
                                    })
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Create a plugin',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create a new plugin by creating a new file `posthog.client.js` in your plugins directory:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'plugins/posthog.client.js',
                                code: dedent`
                                    import { defineNuxtPlugin } from '#app'
                                    import posthog from 'posthog-js'

                                    export default defineNuxtPlugin(nuxtApp => {
                                      const runtimeConfig = useRuntimeConfig();
                                      const posthogClient = posthog.init(runtimeConfig.public.posthogPublicKey, {
                                        api_host: runtimeConfig.public.posthogHost,
                                        defaults: runtimeConfig.public.posthogDefaults,
                                        loaded: (posthog) => {
                                          if (import.meta.env.MODE === 'development') posthog.debug();
                                        }
                                      })

                                      return {
                                        provide: {
                                          posthog: () => posthogClient
                                        }
                                      }
                                    })
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Server-side setup',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        To capture events from server routes, install `posthog-node` and instantiate it directly. You
                        can also use it to evaluate feature flags on the server:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-node
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
                        ]}
                    />
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'server/api/example.js',
                                code: dedent`
                                    import { PostHog } from 'posthog-node'

                                    export default defineEventHandler(async (event) => {
                                        const runtimeConfig = useRuntimeConfig()

                                        const posthog = new PostHog(
                                            runtimeConfig.public.posthogPublicKey,
                                            { host: runtimeConfig.public.posthogHost }
                                        )

                                        posthog.capture({
                                            distinctId: 'distinct_id_of_the_user',
                                            event: 'event_name'
                                        })

                                        await posthog.shutdown()
                                    })
                                `,
                            },
                        ]}
                    />
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

export const NuxtInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()
    const steps = getNuxtSteps(CodeBlock, Markdown, CalloutBox, dedent, snippets)

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
