import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'
import { SDK_DEFAULTS_DATE } from './constants'

function RemixExternalImportSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// vite.config.ts
// ... imports and rest of config

export default defineConfig({
  plugins: [
    remix({
      future: {
        v3_fetcherPersist: true,
        v3_relativeSplatPath: true,
        v3_throwAbortReason: true,
        v3_singleFetch: true,
        v3_lazyRouteDiscovery: true,
      },
    }),
    tsconfigPaths(),
  ],
  ssr: {
    noExternal: ["posthog-js", "posthog-js/react"],
  },
});`}
        </CodeSnippet>
    )
}

function RemixPHProviderSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`import { useEffect, useState } from "react";
import posthog from "posthog-js";
import { PostHogProvider } from "posthog-js/react";

export function PHProvider({ children }: { children: React.ReactNode }) {
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    posthog.init("${currentTeam?.api_token}", {
      api_host: "${apiHostOrigin()}",
      defaults: "${SDK_DEFAULTS_DATE}",
      ${
          isPersonProfilesDisabled
              ? ``
              : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
      }
    });

    setHydrated(true);
  }, []);

  if (!hydrated) return <>{children}</>;
  return <PostHogProvider client={posthog}>{children}</PostHogProvider>;
}`}
        </CodeSnippet>
    )
}

function RemixAppClientCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// app/root.tsx
// ... imports
import { PHProvider } from "./provider";

// ... links, meta, etc.

export function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <Meta />
        <Links />
      </head>
      <body>
        <PHProvider>
          {children}
          <ScrollRestoration />
          <Scripts />
        </PHProvider>
      </body>
    </html>
  );
}

export default function App() {
  return <Outlet />;
}`}
        </CodeSnippet>
    )
}

export function SDKInstallRemixJSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Add PostHog to your app</h3>
            <p>
                Start by setting <code>posthog-js</code> and <code>posthog-js/react</code> as external packages in your{' '}
                <code>vite.config.ts</code> file.
            </p>
            <RemixExternalImportSnippet />
            <p>
                Next, create a <code>provider.tsx</code> file in the app folder. In it, set up the PostHog provider to
                initialize after hydration.
            </p>
            <RemixPHProviderSnippet />
            <p>
                Finally, import the <code>PHProvider</code> component in your <code>app/root.tsx</code> file and use it
                to wrap your app.
            </p>
            <RemixAppClientCodeSnippet />
        </>
    )
}
