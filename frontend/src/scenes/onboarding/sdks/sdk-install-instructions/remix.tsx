import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'

function RemixAppClientCodeSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import { RemixBrowser } from "@remix-run/react";
import { startTransition, StrictMode, useEffect } from "react";
import { hydrateRoot } from "react-dom/client";
import posthog from "posthog-js";

function PosthogInit() {
  useEffect(() => {
    posthog.init('${currentTeam?.api_token}', {
      api_host: '${apiHostOrigin()}',
      ${
          isPersonProfilesDisabled
              ? ``
              : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
      }
    });
  }, []);

  return null;
}

startTransition(() => {
  hydrateRoot(
    document,
    <StrictMode>
        <RemixBrowser />
        <PosthogInit/>
    </StrictMode>
  );
});`}
        </CodeSnippet>
    )
}

export function SDKInstallRemixJSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />

            <h3>Initialize</h3>
            <p>
                Go to your <code>app/entry.client.tsx</code> file and initialize PostHog as a component:
            </p>
            <RemixAppClientCodeSnippet />
        </>
    )
}
