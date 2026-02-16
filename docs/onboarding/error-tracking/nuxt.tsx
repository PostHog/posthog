import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getNuxt37Steps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Install the PostHog Nuxt module',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the PostHog Nuxt module using your package manager:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install @posthog/nuxt
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add @posthog/nuxt
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add @posthog/nuxt
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'bun',
                                code: dedent`
                                    bun add @posthog/nuxt
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Add the module to your `nuxt.config.ts` file:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'nuxt.config.ts',
                                code: dedent`
                                  export default defineNuxtConfig({
                                    modules: ['@posthog/nuxt'],
                                    // Enable source maps generation in both vue and nitro
                                    sourcemap: {
                                      client: 'hidden'
                                    },
                                    nitro: {
                                      rollupConfig: {
                                        output: {
                                          sourcemapExcludeSources: false,
                                        },
                                      },
                                    },
                                    posthogConfig: {
                                      publicKey: '<ph_project_api_key>', // Find it in project settings https://app.posthog.com/settings/project
                                      host: 'https://us.i.posthog.com', // Optional: defaults to https://us.i.posthog.com. Use https://eu.i.posthog.com for EU region
                                      clientConfig: {
                                        capture_exceptions: true, // Enables automatic exception capture on the client side (Vue)
                                      },
                                      serverConfig: {
                                        enableExceptionAutocapture: true, // Enables automatic exception capture on the server side (Nitro)
                                      },
                                      sourcemaps: {
                                        enabled: true,
                                        envId: '<ph_environment_id>', // Your project ID from PostHog settings https://app.posthog.com/settings/environment#variables
                                        personalApiKey: '<ph_personal_api_key>', // Your personal API key from PostHog settings https://app.posthog.com/settings/user-api-keys (requires organization:read and error_tracking:write scopes)
                                        project: 'my-application', // Optional: defaults to git repository name
                                        version: '1.0.0', // Optional: defaults to current git commit
                                      },
                                    },
                                  })
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="Personal API Key">
                        <Markdown>
                            Your Personal API Key will require `organization:read` and `error_tracking:write` scopes.
                        </Markdown>
                    </CalloutBox>
                    <Markdown>
                      {dedent`
                        The module will automatically:
                        - Initialize PostHog on both Vue (client side) and Nitro (server side)
                        - Capture exceptions on both client and server
                        - Generate and upload source maps during build
                      `}
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Manually capturing exceptions',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        {dedent`
                            Our module if set up as shown above already captures both client and server side exceptions automatically.

                            To send errors manually on the client side, import it and use the \`captureException\` method like this:
                        `}
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'Vue',
                                code: dedent`
                                  <script>
                                    const { $posthog } = useNuxtApp()
                                    if ($posthog) {
                                      const posthog = $posthog()
                                      posthog.captureException(new Error("Important error message"))
                                    }
                                  </script>
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        On the server side instantiate PostHog using:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'server/api/example.js',
                                code: dedent`
                                  const runtimeConfig = useRuntimeConfig()
                                  const posthog = new PostHog(
                                    runtimeConfig.public.posthogPublicKey,
                                    {
                                      host: runtimeConfig.public.posthogHost,
                                    }
                                  );
                                  try {
                                    const results = await DB.query.users.findMany()
                                    return results
                                  } catch (error) {
                                    posthog.captureException(error)
                                  }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Build your project for production',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Build your project for production by running the following command:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    nuxt build
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        The PostHog module will automatically **generate and upload source maps** to PostHog during the build process.
                    </Markdown>
                </>
            ),
        },
        {
            title: 'Verify source map upload',
            badge: 'recommended',
            checkpoint: true,
            content: (
                <Markdown>
                    {dedent`
                        Before proceeding, confirm that source maps are being properly uploaded.

                        You can verify the injection is successful by checking your \`.mjs.map\` source map files for \`//# chunkId=\` comments. Make sure to serve these injected files in production, PostHog will check for the \`//# chunkId\` comments to display the correct stack traces.

                        [Check symbol sets in PostHog](https://app.posthog.com/settings/project-error-tracking#error-tracking-symbol-sets)
                    `}
                </Markdown>
            ),
        },
        {
            title: 'Verify error tracking',
            badge: 'recommended',
            checkpoint: true,
            content: (
                <Markdown>
                    {dedent`
                        Before proceeding, let's make sure exception events are being captured and sent to PostHog. You should see events appear in the activity feed.

                        [Check for exceptions in PostHog](https://app.posthog.com/activity/explore)
                    `}
                </Markdown>
            ),
        },
    ]
}

export const Nuxt37Installation = createInstallation(getNuxt37Steps)
