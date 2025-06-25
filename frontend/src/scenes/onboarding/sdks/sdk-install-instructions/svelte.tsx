import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'
import { SDK_DEFAULTS_DATE } from './constants'

function SvelteAppClientCodeSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    const options = [`api_host: '${apiHostOrigin()}'`, `defaults: '${SDK_DEFAULTS_DATE}'`]

    if (!isPersonProfilesDisabled) {
        options.push(
            "person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well"
        )
    }

    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import posthog from 'posthog-js'
import { browser } from '$app/environment';
import { onMount } from 'svelte';

export const load = async () => {
  if (browser) {
    posthog.init(
      '${currentTeam?.api_token}',
      {
        ${options.join(',\n        ')}
      }
    )
  }

  return
};`}
        </CodeSnippet>
    )
}

export function SDKInstallSvelteJSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />

            <h3>Initialize</h3>
            <p>
                If you haven't created a root{' '}
                <Link to="https://kit.svelte.dev/docs/routing#layout" target="_blank">
                    layout
                </Link>{' '}
                already, create a new file called <code>+layout.js</code> in your <code>src/routes</code> folder. In
                this file, check the environment is the browser, and initialize PostHog if so:
            </p>
            <SvelteAppClientCodeSnippet />
        </>
    )
}
