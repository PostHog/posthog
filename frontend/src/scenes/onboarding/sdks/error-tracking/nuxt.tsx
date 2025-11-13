import { useValues } from 'kea'
import { useState } from 'react'

import { LemonTabs, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { SDK_DEFAULTS_DATE } from '../sdk-install-instructions/constants'
import { JSInstallSnippet } from '../sdk-install-instructions/js-web'
import { JSManualCapture } from './FinalSteps'

export type NuxtVersion = 'v3.7+' | 'v3.6-'

export function NuxtInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const [nuxtVersion, setNuxtVersion] = useState<NuxtVersion>('v3.7+')
    const host = apiHostOrigin()

    return (
        <>
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
                <NuxtModuleInstructions
                    apiKey={currentTeam?.api_token ?? '<ph_project_api_key>'}
                    host={host}
                    teamId={currentTeam?.id?.toString() ?? '<team_id>'}
                />
            ) : (
                <NuxtLegacyInstructions apiKey={currentTeam?.api_token ?? '<ph_project_api_key>'} host={host} />
            )}
        </>
    )
}

function NuxtModuleInstructions({
    apiKey,
    host,
    teamId,
}: {
    apiKey: string
    host: string
    teamId: string
}): JSX.Element {
    return (
        <>
            <h3>Install the PostHog Nuxt module</h3>
            <p>Install the PostHog Nuxt module using your package manager:</p>
            <CodeSnippet language={Language.Bash}>
                {['npm install @posthog/nuxt', '# OR', 'yarn add @posthog/nuxt', '# OR', 'pnpm add @posthog/nuxt'].join(
                    '\n'
                )}
            </CodeSnippet>
            <p>
                Add the module to your <code>nuxt.config.ts</code> file:
            </p>
            <CodeSnippet language={Language.TypeScript}>{nuxtModuleConfig(apiKey, host, teamId)}</CodeSnippet>
            <h3>Upload source maps</h3>
            <p>
                Source maps will be automatically generated and uploaded to PostHog during the build process when you
                run <code>nuxt build</code>. No additional steps are required.
            </p>
            <h3>Manually capturing exceptions (optional)</h3>
            <p>
                Our module, if set up as shown above already captures both client and server side exceptions
                automatically.
            </p>
            <p>To send errors manually on the client side:</p>
            <CodeSnippet language={Language.JavaScript}>{manualClientCapture}</CodeSnippet>
            <p>To send errors manually on the server side:</p>
            <CodeSnippet language={Language.JavaScript}>{manualServerCapture}</CodeSnippet>
        </>
    )
}

function NuxtLegacyInstructions({ apiKey, host }: { apiKey: string; host: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    return (
        <>
            <h3>Install PostHog SDK</h3>
            <p>
                The below guide is for Nuxt v3.0 and above. For Nuxt v2.16 and below, see our{' '}
                <Link to="https://posthog.com/docs/libraries/nuxt-js#nuxt-v216-and-below">Nuxt docs</Link>
            </p>
            <h4>Install posthog-js using your package manager</h4>
            <JSInstallSnippet />
            <h4>Add environment variables</h4>
            <p>
                Add your PostHog API key and host to your <code>nuxt.config.js</code> file.
            </p>
            <CodeSnippet language={Language.JavaScript}>
                {`export default defineNuxtConfig({
  runtimeConfig: {
    public: {
      posthogPublicKey: '${apiKey}',
      posthogHost: '${host}',
      posthogDefaults: '${SDK_DEFAULTS_DATE}'
    }
  }
})`}
            </CodeSnippet>
            <h4>Create a plugin</h4>
            <p>
                Create a new plugin by creating a new file <code>posthog.client.js</code> in your{' '}
                <Link to="https://nuxt.com/docs/guide/directory-structure/plugins" target="_blank">
                    plugins directory
                </Link>
                :
            </p>
            <CodeSnippet language={Language.JavaScript}>
                {`import { defineNuxtPlugin } from '#app'
import posthog from 'posthog-js'
export default defineNuxtPlugin(nuxtApp => {
  const runtimeConfig = useRuntimeConfig();
  const posthogClient = posthog.init(runtimeConfig.public.posthogPublicKey, {
    api_host: runtimeConfig.public.posthogHost,
    defaults: runtimeConfig.public.posthogDefaults,
    ${
        isPersonProfilesDisabled
            ? ``
            : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
    }
    loaded: (posthog) => {
      if (import.meta.env.MODE === 'development') posthog.debug();
    }
  })

  return {
    provide: {
      posthog: () => posthogClient
    }
  }
})`}
            </CodeSnippet>
            <h3>Configure exception autocapture</h3>
            <p>
                Update your <code>posthog.client.js</code> to add an error hook:
            </p>
            <CodeSnippet language={Language.JavaScript}>{legacyClientErrorHandling}</CodeSnippet>
            <p>
                For server-side errors, create a server plugin <code>posthog.server.js</code> in your{' '}
                <code>plugins</code> directory:
            </p>
            <CodeSnippet language={Language.JavaScript}>{legacyServerErrorHandling}</CodeSnippet>
            <JSManualCapture />
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
    host: '${host}',
    clientConfig: {
      capture_exceptions: true, // Enables automatic exception capture on the client side (Vue)
    },
    serverConfig: {
      enableExceptionAutocapture: true, // Enables automatic exception capture on the server side (Nitro)
    },
    sourcemaps: {
      enabled: true,
      envId: '${teamId}',
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

const manualServerCapture = `// server/api/example.js
export default defineEventHandler(async (event) => {
  const { PostHog } = await import('posthog-node');
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
})`

const legacyClientErrorHandling = `// plugins/posthog.client.js
export default defineNuxtPlugin((nuxtApp) => {
    const runtimeConfig = useRuntimeConfig();
    const posthogClient = posthog.init(runtimeConfig.public.posthogPublicKey, {
        api_host: runtimeConfig.public.posthogHost,
        defaults: runtimeConfig.public.posthogDefaults,
        person_profiles: 'identified_only',
        capture_exceptions: true, // Enables automatic exception capture on the client side (Vue)
        loaded: (posthog) => {
            if (import.meta.env.MODE === 'development') posthog.debug();
        }
    })

    return {
        provide: {
            posthog: () => posthogClient
        }
    }
})`

const legacyServerErrorHandling = `// plugins/posthog.server.js
import { defineNuxtPlugin } from '#app'
import { PostHog } from 'posthog-node'

const runtimeConfig = useRuntimeConfig()

export default defineNuxtPlugin((nuxtApp) => {
  const posthogServer = new PostHog(runtimeConfig.public.posthogPublicKey, {
    host: runtimeConfig.public.posthogHost,
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
