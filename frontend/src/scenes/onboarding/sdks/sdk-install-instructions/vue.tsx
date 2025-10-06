import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { SDK_DEFAULTS_DATE } from './constants'
import { JSInstallSnippet } from './js-web'

function VueCreateComposableFileSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import posthog from 'posthog-js'

export function usePostHog() {
  posthog.init('${currentTeam?.api_token}', {
    api_host: '${apiHostOrigin()}',
    defaults: '${SDK_DEFAULTS_DATE}',
    ${
        isPersonProfilesDisabled
            ? ``
            : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
    }
  })

  return { posthog }
}`}
        </CodeSnippet>
    )
}

function VueComposableCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import { usePostHog } from '@/composables/usePostHog'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/about',
      name: 'about',
      component: () => import('../views/AboutView.vue'),
    },
  ],
})

const { posthog } = usePostHog()

export default router`}
        </CodeSnippet>
    )
}

export function SDKInstallVueInstructions(): JSX.Element {
    return (
        <>
            <p>
                The below guide is for integrating using plugins in Vue versions 3 and above. For integrating PostHog
                using Provide/inject, Vue.prototype, or versions 2.7 and below, see our{' '}
                <Link to="https://posthog.com/docs/libraries/vue-js">Vue docs</Link>
            </p>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Add Posthog to your app</h3>
            <p>
                Create a new file <code>src/composables/usePostHog.js</code>:
            </p>
            <VueCreateComposableFileSnippet />
            <br />
            Next, in <code>router/index.js</code>, import the <code>usePostHog</code> composable and call it:
            <VueComposableCodeSnippet />
        </>
    )
}
