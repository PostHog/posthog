import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const NuxtInstallation = (): JSX.Element => {
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
                <CalloutBox type="fyi" title="Nuxt version">
                    <Markdown>
                        This guide is for Nuxt v3.0 and above. For Nuxt v2.16 and below, see our [Nuxt
                        docs](https://posthog.com/docs/libraries/nuxt-js#nuxt-v216-and-below).
                    </Markdown>
                </CalloutBox>
            </Step>

            <Step title="Add environment variables" badge="required">
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
            </Step>

            <Step title="Create a plugin" badge="required">
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
            </Step>

            <Step title="Server-side setup" badge="optional">
                <Markdown>
                    To capture events from server routes, install `posthog-node` and instantiate it directly:
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
            </Step>

            <Step title="Send events">{JSEventCapture && <JSEventCapture />}</Step>
        </Steps>
    )
}
