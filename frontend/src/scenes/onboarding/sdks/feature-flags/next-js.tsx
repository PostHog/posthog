import { Link } from 'lib/lemon-ui/Link'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { JSInstallSnippet, SessionReplayFinalSteps } from '../shared-snippets'

function NextEnvVarsSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <CodeSnippet language={Language.Bash}>
            {[
                `NEXT_PUBLIC_POSTHOG_KEY=${currentTeam?.api_token}`,
                `NEXT_PUBLIC_POSTHOG_HOST=${window.location.origin}`,
            ].join('\n')}
        </CodeSnippet>
    )
}

function NextPagesRouterCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// pages/_app.js
...
import posthog from 'posthog-js' // Import PostHog

if (typeof window !== 'undefined') { // checks that we are client-side
  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://app.posthog.com',
    loaded: (posthog) => {
      if (process.env.NODE_ENV === 'development') posthog.debug() // debug mode in development
    },
  })
}

export default function App({ Component, pageProps }) {
  const router = useRouter()
  ...`}
        </CodeSnippet>
    )
}

function NextAppRouterCodeSnippet(): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript}>
            {`// app/providers.js
'use client'
...
import posthog from 'posthog-js'

if (typeof window !== 'undefined') {
  posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY, {
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
  })
}
...`}
        </CodeSnippet>
    )
}

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <h3>Install posthog-js using your package manager</h3>
            <JSInstallSnippet />
            <h3>Add environment variables</h3>
            <p>
                Add your environment variables to your .env.local file and to your hosting provider (e.g. Vercel,
                Netlify, AWS). You can find your project API key in your project settings.
            </p>
            <p className="italic">
                These values need to start with <code className="not-italic">NEXT_PUBLIC_</code> to be accessible on the
                client-side.
            </p>
            <NextEnvVarsSnippet />

            <h3>Initialize</h3>
            <h4>With App router</h4>
            <p>
                If your Next.js app to uses the <Link to="https://nextjs.org/docs/app">app router</Link>, you can
                integrate PostHog by creating a providers file in your app folder. This is because the posthog-js
                library needs to be initialized on the client-side using the Next.js{' '}
                <Link to="https://nextjs.org/docs/getting-started/react-essentials#client-components" target="_blank">
                    <code>'use client'</code> directive
                </Link>
                .
            </p>
            <NextAppRouterCodeSnippet />
            <h4>With Pages router</h4>
            <p>
                If your Next.js app uses the <Link to={'https://nextjs.org/docs/pages'}>pages router</Link>, you can
                integrate PostHog at the root of your app (pages/_app.js).
            </p>
            <NextPagesRouterCodeSnippet />
            <SessionReplayFinalSteps />
        </>
    )
}
