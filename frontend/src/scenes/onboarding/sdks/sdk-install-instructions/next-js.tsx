import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { JSInstallSnippet } from './js-web'

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

function NextPagesRouterCodeSnippet(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// pages/_app.js
import { useEffect } from 'react'
import { Router } from 'next/router'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'

export default function App({ Component, pageProps }) {

  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
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

function NextPagesRouterPageViewSnippet(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// pages/_app.js
import { useEffect } from 'react'
import { Router } from 'next/router'
import posthog from 'posthog-js'
import { PostHogProvider } from 'posthog-js/react'

export default function App({ Component, pageProps }) {

  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://us.i.posthog.com',
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

function NextAppRouterCodeSnippet(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// app/providers.jsx
'use client'
import posthog from 'posthog-js'
import { PostHogProvider as PHProvider } from 'posthog-js/react'
import { useEffect } from 'react'

export function PostHogProvider({ children }) {
  useEffect(() => {
    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
      ${
          isPersonProfilesDisabled
              ? ``
              : `person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users as well`
      }
    })
  }, [])

  return (
    <PHProvider client={posthog}>
      {children}
    </PHProvider>
  )
}`}
        </CodeSnippet>
    )
}

function NextAppRouterLayoutSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// app/layout.jsx
import './globals.css'
import { PostHogProvider } from './providers'

export default function RootLayout({ children }) {
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

function NextAppRouterPageViewSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// app/PostHogPageView.jsx
'use client'

import { usePathname, useSearchParams } from "next/navigation"
import { useEffect, Suspense } from "react"
import { usePostHog } from 'posthog-js/react'

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

// Wrap this in Suspense to avoid the useSearchParams usage above
// from de-opting the whole app into client-side rendering
// See: https://nextjs.org/docs/messages/deopted-into-client-rendering
export default function SuspendedPostHogPageView() {
  return <Suspense fallback={null}>
    <PostHogPageView />
  </Suspense>
}`}
        </CodeSnippet>
    )
}

function NextAppRouterPageViewProviderSnippet(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// app/providers.jsx
'use client'
import posthog from 'posthog-js'
import { PostHogProvider as PHProvider } from 'posthog-js/react'
import { useEffect } from 'react'
import PostHogPageView from "./PostHogPageView"

export function PostHogProvider({ children }) {
    useEffect(() => {
        posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
            api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
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
        <PostHogPageView />
        {children}
    </PHProvider>
)
}`}
        </CodeSnippet>
    )
}

export function SDKInstallNextJSInstructions(): JSX.Element {
    return (
        <>
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
            <h4>With App router</h4>
            <p>
                If your Next.js app uses the{' '}
                <Link to="https://nextjs.org/docs/app" target="_blank">
                    app router
                </Link>
                , you can integrate PostHog by creating a <code>providers</code> file in your <code>app</code> folder.
                This is because the <code>posthog-js</code> library needs to be initialized on the client-side using the
                Next.js{' '}
                <Link to="https://nextjs.org/docs/getting-started/react-essentials#client-components" target="_blank">
                    <code>'use client'</code> directive
                </Link>
                .
            </p>
            <NextAppRouterCodeSnippet />
            <p>
                Afterwards, import the <code>PostHogProvider</code> component in your <code>app/layout.jsx</code> file
                and wrap your app with it.
            </p>
            <NextAppRouterLayoutSnippet />
            <h4>With Pages router</h4>
            <p>
                If your Next.js app uses the{' '}
                <Link to="https://nextjs.org/docs/pages" target="_blank">
                    pages router
                </Link>
                , you can integrate PostHog at the root of your app.
            </p>
            <NextPagesRouterCodeSnippet />
            <h3>Capturing pageviews</h3>
            <p>
                PostHog's <code>$pageview</code> autocapture relies on page load events. Since Next.js acts as a
                single-page app, this event doesn't trigger on navigation and we need to capture <code>$pageview</code>{' '}
                events manually.
            </p>
            <h4>With App router</h4>
            <p>
                Set up a <code>PostHogPageView</code> component to listen to URL changes.
            </p>
            <NextAppRouterPageViewSnippet />
            <p>
                We can then update our <code>PostHogProvider</code> to include this component in all of our pages.
            </p>
            <NextAppRouterPageViewProviderSnippet />
            <h4>With Pages router</h4>
            <p>
                We can set up a <code>handleRouteChange</code> function to capture pageviews in the{' '}
                <code>useEffect</code> hook in <code>pages/_app.js</code>.
            </p>
            <NextPagesRouterPageViewSnippet />
        </>
    )
}
