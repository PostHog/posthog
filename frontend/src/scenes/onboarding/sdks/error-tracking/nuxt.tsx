import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { SDKInstallNuxtJSInstructions } from '../sdk-install-instructions/nuxt'
import { JSManualCapture } from './FinalSteps'
import { type NuxtVersion, nuxtInstructionsLogic } from './nuxtInstructionsLogic'

export function NuxtInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { nuxtVersion } = useValues(nuxtInstructionsLogic)
    const { setNuxtVersion } = useActions(nuxtInstructionsLogic)
    const host = apiHostOrigin()

    return (
        <>
            <p>
                For Nuxt v3.7 and above, we recommend using the official <code>@posthog/nuxt</code> module which
                provides automatic error tracking with built-in source map support.
            </p>
            <LemonTabs
                activeKey={nuxtVersion}
                onChange={(key) => setNuxtVersion(key as NuxtVersion)}
                tabs={[
                    {
                        key: 'v3.7+',
                        label: 'Nuxt v3.7+',
                    },
                    {
                        key: 'v3.6-',
                        label: 'Nuxt v3.6 and below',
                    },
                ]}
            />
            {nuxtVersion === 'v3.7+' ? (
                <NuxtModuleInstructions apiKey={currentTeam?.api_token ?? '<ph_project_api_key>'} host={host} />
            ) : (
                <NuxtLegacyInstructions apiKey={currentTeam?.api_token ?? '<ph_project_api_key>'} host={host} />
            )}
        </>
    )
}

function NuxtModuleInstructions({ apiKey, host }: { apiKey: string; host: string }): JSX.Element {
    return (
        <>
            <h3>Install the PostHog Nuxt module</h3>
            <p>Install the PostHog Nuxt module using your package manager:</p>
            <CodeSnippet language={Language.Bash}>npm install @posthog/nuxt</CodeSnippet>
            <p>
                Add the module to your <code>nuxt.config.ts</code> file:
            </p>
            <CodeSnippet language={Language.TypeScript}>{nuxtModuleConfig(apiKey, host)}</CodeSnippet>
            <h3>Upload source maps</h3>
            <p>
                Source maps will be automatically generated and uploaded to PostHog during the build process when you
                run <code>nuxt build</code>. No additional steps are required.
            </p>
            <h3>Manually capturing exceptions (optional)</h3>
            <p>
                Our module if set up as shown above already captures both client and server side exceptions
                automatically.
            </p>
            <p>
                To send errors manually on the client side, import it and use the <code>captureException</code> method
                like this:
            </p>
            <CodeSnippet language={Language.JavaScript}>{manualClientCapture}</CodeSnippet>
            <p>On the server side instantiate PostHog using:</p>
            <CodeSnippet language={Language.JavaScript}>{manualServerCapture(apiKey, host)}</CodeSnippet>
        </>
    )
}

function NuxtLegacyInstructions({ apiKey, host }: { apiKey: string; host: string }): JSX.Element {
    return (
        <>
            <h3>Install PostHog SDK</h3>
            <p>
                The below guide is for Nuxt v3.6 and below. For Nuxt v3.7 and above, see the <strong>Nuxt v3.7+</strong>{' '}
                tab.
            </p>
            <SDKInstallNuxtJSInstructions />
            <h3>Configure exception autocapture</h3>
            <p>
                Update your <code>posthog.client.js</code> to add an error hook:
            </p>
            <CodeSnippet language={Language.JavaScript}>{legacyClientErrorHandling}</CodeSnippet>
            <p>
                For server-side errors, create a server plugin <code>posthog.server.js</code> in your{' '}
                <code>plugins</code> directory:
            </p>
            <CodeSnippet language={Language.JavaScript}>{legacyServerErrorHandling(apiKey, host)}</CodeSnippet>
            <JSManualCapture />
            <h3>Upload source maps</h3>
            <p>
                To see readable stack traces, you'll need to upload source maps. First, install the{' '}
                <code>posthog-cli</code>:
            </p>
            <CodeSnippet language={Language.Bash}>
                {`curl --proto '=https' --tlsv1.2 -LsSf https://github.com/PostHog/posthog/releases/download/posthog-cli-v0.0.2/posthog-cli-installer.sh | sh
posthog-cli-update`}
            </CodeSnippet>
            <p>After building your application, inject and upload source maps:</p>
            <CodeSnippet language={Language.Bash}>
                {`posthog-cli sourcemap inject --directory ./path/to/assets
posthog-cli sourcemap upload --directory ./path/to/assets`}
            </CodeSnippet>
        </>
    )
}

const nuxtModuleConfig = (apiKey: string, host: string): string => `export default defineNuxtConfig({
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
    host: '${host}',
    clientConfig: {
      capture_exceptions: true, // Enables automatic exception capture on the client side (Vue)
    },
    serverConfig: {
      enableExceptionAutocapture: true, // Enables automatic exception capture on the server side (Nitro)
    },
    sourcemaps: {
      enabled: true,
      envId: '<ph_environment_id>', // Your environment ID from PostHog settings
      personalApiKey: '<ph_personal_api_key>', // Your personal API key from PostHog settings
      project: 'my-application', // Optional: defaults to git repository name
      version: '1.0.0', // Optional: defaults to current git commit
    },
  },
})`

const manualClientCapture = `// component.vue
<script>
  const { $posthog } = useNuxtApp()

  if ($posthog) {
    const posthog = $posthog()
    posthog.captureException(new Error("Important error message"))
  }
</script>`

const manualServerCapture = (apiKey: string, host: string): string => `// server/api/example.js
export default defineEventHandler(async (event) => {
  const distinctId = getCookie(event, 'distinct_id')

  const { PostHog } = await import('posthog-node');
  const runtimeConfig = useRuntimeConfig()

  const posthog = new PostHog(
    '${apiKey}',
    { 
      host: '${host}', 
    }
  );

  try {
    const results = await DB.query.users.findMany()
    return results
  } catch (error) {
    posthog.captureException(error)
  }
})`

const legacyClientErrorHandling = `// plugins/posthog.client.js
export default defineNuxtPlugin((nuxtApp) => {
    const runtimeConfig = useRuntimeConfig();
    const posthogClient = posthog.init(runtimeConfig.public.posthogPublicKey, {
        api_host: runtimeConfig.public.posthogHost,
        defaults: runtimeConfig.public.posthogDefaults,
        person_profiles: 'identified_only',
        loaded: (posthog) => {
            if (import.meta.env.MODE === 'development') posthog.debug();
        }
    })

    // Capture Vue errors
    nuxtApp.hook('vue:error', (error) => {
        posthogClient.captureException(error)
    })

    return {
        provide: {
            posthog: () => posthogClient
        }
    }
})`

const legacyServerErrorHandling = (apiKey: string, host: string): string => `// plugins/posthog.server.js
import { defineNuxtPlugin } from '#app'
import { PostHog } from 'posthog-node'

export default defineNuxtPlugin((nuxtApp) => {
  const posthogServer = new PostHog('${apiKey}', {
    host: '${host}',
  })

  // Capture server errors
  nuxtApp.hook('app:error', (error) => {
    posthogServer.captureException(error)
  })

  // Ensure we flush events on server shutdown
  nuxtApp.hook('close', async () => {
    await posthogServer.shutdown()
  })

  return {
    provide: {
      posthogServer: () => posthogServer
    }
  }
})`
