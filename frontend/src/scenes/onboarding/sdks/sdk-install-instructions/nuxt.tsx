import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { Link } from 'lib/lemon-ui/Link'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'
import { NodeInstallSnippet } from './nodejs'

function NuxtEnvVarsSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.JavaScript}>
            {`export default defineNuxtConfig({
                runtimeConfig: {
                  public: {
                    posthogPublicKey: '${currentTeam?.api_token}',
                    posthogHost: '${apiHostOrigin()}'
                  }
                }
              })`}
        </CodeSnippet>
    )
}

function NuxtAppClientCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import { defineNuxtPlugin } from '#app'
import posthog from 'posthog-js'
export default defineNuxtPlugin(nuxtApp => {
  const runtimeConfig = useRuntimeConfig();
  const posthogClient = posthog.init(runtimeConfig.public.posthogPublicKey, {
    api_host: runtimeConfig.public.posthogHost',
    capture_pageview: false, // we add manual pageview capturing below
    loaded: (posthog) => {
      if (import.meta.env.MODE === 'development') posthog.debug();
    }
  })

  // Make sure that pageviews are captured with each route change
  const router = useRouter();
  router.afterEach((to) => {
    nextTick(() => {
      posthog.capture('$pageview', {
        current_url: to.fullPath
      });
    });
  });

  return {
    provide: {
      posthog: () => posthogClient
    }
  }
})`}
        </CodeSnippet>
    )
}

function NuxtAppServerCode(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`<!-- ...rest of code -->

<script setup>
import { useAsyncData, useCookie, useRuntimeConfig } from 'nuxt/app';
import { PostHog } from 'posthog-node';

const { data: someData, error } = await useAsyncData('example', async () => {
  const runtimeConfig = useRuntimeConfig();
  const posthog = new PostHog(
    runtimeConfig.public.posthogPublicKey,
    { host: runtimeConfig.public.posthogHost }
  );

  // rest of your code

});

</script>`}
        </CodeSnippet>
    )
}

export function SDKInstallNuxtJSInstructions(): JSX.Element {
    return (
        <>
            <p>
                The below guide is for Nuxt v3.0 and above. For Nuxt v2.16 and below, see our{' '}
                <Link to="https://posthog.com/docs/libraries/nuxt-js#nuxt-v216-and-below">Nuxt docs</Link>
            </p>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Add environment variables</h3>
            <p>
                Add your PostHog API key and host to your <code>nuxt.config.js</code> file.
            </p>
            <NuxtEnvVarsSnippet />

            <h3>Create a plugin</h3>
            <p>
                Create a new plugin by creating a new file <code>posthog.client.js</code> in your{' '}
                <Link to="https://nuxt.com/docs/guide/directory-structure/plugins" target="_blank">
                    plugins directory
                </Link>
                :
            </p>
            <NuxtAppClientCodeSnippet />
            <h3>Server-side integration</h3>
            <p>Install posthog-node using your package manager</p>
            <NodeInstallSnippet />
            <h3>Server-side initialization</h3>
            <p>
                Initialize the PostHog Node client where you'd like to use it on the server side. For example, in{' '}
                <Link to="https://nuxt.com/docs/api/composables/use-async-data" target="_blank">
                    useAsyncData
                </Link>
                :{' '}
            </p>
            <NuxtAppServerCode />
        </>
    )
}
