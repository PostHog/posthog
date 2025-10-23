import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { VerifySourceMaps } from '../VerifySourceMaps'

export function NuxtSourceMapsInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const host = apiHostOrigin()

    return (
        <>
            <p>
                For Nuxt v3.7 and above, the official <code>@posthog/nuxt</code> module provides automatic source map
                generation and upload.
            </p>

            <h3>Install the PostHog Nuxt module</h3>
            <p>Install the PostHog Nuxt module using your package manager:</p>
            <CodeSnippet language={Language.Bash}>
                {['npm install @posthog/nuxt', '# OR', 'yarn add @posthog/nuxt', '# OR', 'pnpm add @posthog/nuxt'].join(
                    '\n'
                )}
            </CodeSnippet>

            <h3>Add PostHog config to your Nuxt app</h3>
            <p>
                Add the module to your <code>nuxt.config.ts</code> file:
            </p>
            <CodeSnippet language={Language.TypeScript}>
                {nuxtModuleConfig(
                    currentTeam?.api_token ?? '<ph_project_api_key>',
                    host,
                    currentTeam?.id?.toString() ?? '<team_id>'
                )}
            </CodeSnippet>

            <h3>Build your project for production</h3>
            <p>
                Build your project for production. The PostHog module will automatically generate and upload source maps
                to PostHog during the build process.
            </p>

            <VerifySourceMaps />
        </>
    )
}

const nuxtModuleConfig = (apiKey: string, host: string, teamId: string): string => `export default defineNuxtConfig({
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
    publicKey: '${apiKey}',
    host: '${host}', // Optional: Your PostHog instance URL, defaults to https://us.posthog.com
    clientConfig: {
      capture_exceptions: true, // Enables automatic exception capture on the client side (Vue)
    },
    serverConfig: {
      enableExceptionAutocapture: true, // Enables automatic exception capture on the server side (Nitro)
    },
    sourcemaps: {
      enabled: true,
      envId: '${teamId}', // Your environment ID (project ID)
      personalApiKey: '<ph_personal_api_key>', // Your personal API key from PostHog settings
      project: 'my-application', // Optional: Project name, defaults to git repository name
      version: '1.0.0', // Optional: Release version, defaults to current git commit
    },
  },
})`
