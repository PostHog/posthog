import { LemonDivider, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'

import SetupWizardBanner from './components/SetupWizardBanner'
import { JSInstallSnippet } from './js-web'
import { nextJsInstructionsLogic, type NextJSRouter } from './nextJsInstructionsLogic'

function NextEnvVarsSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Bash}>
            {[`NEXT_PUBLIC_POSTHOG_KEY=${currentTeam?.api_token}`, `NEXT_PUBLIC_POSTHOG_HOST=${apiHostOrigin()}`].join(
                '\n'
            )}
        </CodeSnippet>
    )
}

function NextPagesRouterPageViewSnippet(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.TypeScript}>
            {`// pages/_app.tsx
import { useEffect } from 'react'
import { Router } from 'next/router'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'
import type { AppProps } from 'next/app'

export default function App({ Component, pageProps }: AppProps) {

  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY as string, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || '${apiHostOrigin()}',
      ${
          isPersonProfilesDisabled
              ? ``
              : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
      }
      // Enable debug mode in development
      loaded: (posthog) => {
        if (process.env.NODE_ENV === 'development') posthog.debug()
      }
    })

    const handleRouteChange = () => posthog?.capture('$pageview')

    Router.events.on('routeChangeComplete', handleRouteChange);

    return () => {
      Router.events.off('routeChangeComplete', handleRouteChange);
    }
  }, [])

  return (
    <PostHogProvider client={posthog}>
      <Component {...pageProps} />
    </PostHogProvider>
  )
}`}
        </CodeSnippet>
    )
}

function NextAppRouterLayoutSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.TypeScript}>
            {`// app/layout.tsx

import './globals.css'
import { PostHogProvider } from './providers'

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PostHogProvider>
          {children}
        </PostHogProvider>
      </body>
    </html>
  )
}`}
        </CodeSnippet>
    )
}

function NextAppRouterPageViewProviderSnippet(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.TypeScript}>
            {`// app/providers.tsx
'use client'

import { usePathname, useSearchParams } from "next/navigation"
import { useEffect, Suspense } from "react"
import { usePostHog } from 'posthog-js/react'

import posthog from 'posthog-js'
import { PostHogProvider as PHProvider } from 'posthog-js/react'

export function PostHogProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY as string, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || '${apiHostOrigin()}',
      ${
          isPersonProfilesDisabled
              ? ``
              : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
      }
      capture_pageview: false // Disable automatic pageview capture, as we capture manually
    })
  }, [])

  return (
    <PHProvider client={posthog}>
      <SuspendedPostHogPageView />
      {children}
    </PHProvider>
  )
}

function PostHogPageView() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const posthog = usePostHog()

  // Track pageviews
  useEffect(() => {
    if (pathname && posthog) {
      let url = window.origin + pathname
      if (searchParams.toString()) {
        url = url + "?" + searchParams.toString();
      }

      posthog.capture('$pageview', { '$current_url': url })
    }
  }, [pathname, searchParams, posthog])

  return null
}

// Wrap PostHogPageView in Suspense to avoid the useSearchParams usage above
// from de-opting the whole app into client-side rendering
// See: https://nextjs.org/docs/messages/deopted-into-client-rendering
function SuspendedPostHogPageView() {
  return (
    <Suspense fallback={null}>
      <PostHogPageView />
    </Suspense>
  )
}`}
        </CodeSnippet>
    )
}

export function SDKInstallNextJSInstructions({ hideWizard }: { hideWizard?: boolean }): JSX.Element {
    const { nextJsRouter } = useValues(nextJsInstructionsLogic)
    const { setNextJsRouter } = useActions(nextJsInstructionsLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const showSetupWizard = useFeatureFlag('AI_SETUP_WIZARD') && !hideWizard && isCloudOrDev

    return (
        <>
            {showSetupWizard && (
                <>
                    <h2>Automated Installation</h2>
                    <SetupWizardBanner integrationName="Next.js" />
                    <LemonDivider label="OR" />
                    <h2>Manual Installation</h2>
                </>
            )}
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Add environment variables</h3>
            <p>
                Add your environment variables to your .env.local file and to your hosting provider (e.g. Vercel,
                Netlify, AWS). You can find your project API key in your project settings.
            </p>
            <p>
                These values need to start with <code>NEXT_PUBLIC_</code> to be accessible on the client-side.
            </p>
            <NextEnvVarsSnippet />

            <h3>Initialize</h3>

            <LemonTabs
                activeKey={nextJsRouter}
                onChange={(key) => setNextJsRouter(key as NextJSRouter)}
                tabs={[
                    {
                        key: 'app',
                        label: 'App router',
                    },
                    {
                        key: 'pages',
                        label: 'Pages router',
                    },
                ]}
            />
            {nextJsRouter === 'app' && (
                <>
                    <p>
                        If your Next.js app uses the{' '}
                        <Link to="https://nextjs.org/docs/app" target="_blank">
                            app router
                        </Link>
                        , you can integrate PostHog by creating a <code>providers</code> file in your <code>app</code>{' '}
                        folder. This is because the <code>posthog-js</code> library needs to be initialized on the
                        client-side using the Next.js{' '}
                        <Link
                            to="https://nextjs.org/docs/getting-started/react-essentials#client-components"
                            target="_blank"
                        >
                            <code>'use client'</code> directive
                        </Link>
                        .
                    </p>
                    <NextAppRouterPageViewProviderSnippet />
                    <p>
                        Afterwards, import the <code>PostHogProvider</code> component in your{' '}
                        <code>app/layout.tsx</code> file and wrap your app with it.
                    </p>
                    <NextAppRouterLayoutSnippet />
                </>
            )}
            {nextJsRouter === 'pages' && (
                <>
                    <p>
                        If your Next.js app uses the{' '}
                        <Link to="https://nextjs.org/docs/pages" target="_blank">
                            pages router
                        </Link>
                        , you can integrate PostHog at the root of your app.
                    </p>
                    <p>
                        PostHog's <code>$pageview</code> autocapture relies on page load events. Since Next.js acts as a
                        single-page app, this event doesn't trigger on navigation and we need to capture{' '}
                        <code>$pageview</code> events manually.
                    </p>
                    <p>
                        We can set up a <code>handleRouteChange</code> function to capture pageviews in the{' '}
                        <code>useEffect</code> hook in <code>pages/_app.tsx</code>.
                    </p>
                    <NextPagesRouterPageViewSnippet />
                </>
            )}
        </>
    )
}
