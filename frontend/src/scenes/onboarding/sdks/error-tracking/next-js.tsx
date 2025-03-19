import { Link } from '@posthog/lemon-ui'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { JSManualCapture } from './FinalSteps'

export function NextJSInstructions(): JSX.Element {
    return (
        <>
            <SDKInstallNextJSInstructions />
            <h3>Capturing component render errors</h3>
            <p>
                Next.js uses{' '}
                <Link
                    target="_blank"
                    to="https://nextjs.org/docs/app/building-your-application/routing/error-handling#using-error-boundaries"
                >
                    error boundaries
                </Link>{' '}
                to handle uncaught exceptions by rendering a fallback UI instead of the crashing components.
            </p>
            <p>
                To set one up, create a <code>error.tsx</code> file in any of your route directories. This triggers when
                there is an error rendering your component and should look like this:
            </p>
            <CodeSnippet language={Language.JavaScript}>{errorComponent}</CodeSnippet>
            <p>
                You can also create a{' '}
                <Link
                    target="_blank"
                    to="https://nextjs.org/docs/app/building-your-application/routing/error-handling#handling-global-errors"
                >
                    Global Error component
                </Link>{' '}
                in your root layout to capture unhandled exceptions in your root layout.
            </p>
            <CodeSnippet language={Language.JavaScript}>{globalErrorComponent}</CodeSnippet>
            <JSManualCapture />
            <h3>Capturing server errors</h3>
            <p>
                To capture errors that occur in your server-side code, you can set up a{' '}
                <Link
                    target="_blank"
                    to="https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation"
                >
                    instrumentation.ts
                </Link>{' '}
                file at the root of your project. This provides a <code>onRequestError</code> hook that you can use to
                capture errors.
            </p>
            <p>
                You can check the runtime to ensure PostHog works and fetch the <code>distinct_id</code> from the cookie
                to connect the error to a specific user
            </p>
            <CodeSnippet language={Language.TypeScript}>{instrumentationComponent}</CodeSnippet>
        </>
    )
}

const globalErrorComponent = `// app/global-error.tsx

'use client' // Error boundaries must be Client Components

import posthog from "posthog-js";
import NextError from "next/error";
import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    posthog.captureException(error);
  }, [error]);

  return (
    // global-error must include html and body tags
    <html>
      <body>
        {/* \`NextError\` is the default Next.js error page component */}
        <NextError statusCode={0} />
      </body>
    </html>
  )
}
`
const errorComponent = `// error.tsx

"use client";  // Error boundaries must be Client Components

import posthog from "posthog-js";
import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    posthog.captureException(error);
  }, [error]);

  return (
    ...
  );
}
`

const instrumentationComponent = `// instrumentation.ts

export function register() {
  // No-op for initialization
}

export const onRequestError = async (err, request, context) => {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    const { getPostHogServer } = require('./app/posthog-server')
    const posthog = await getPostHogServer()

    let distinctId = null
    if (request.headers.cookie) {
      const cookieString = request.headers.cookie
      const postHogCookieMatch = cookieString.match(/ph_phc_.*?_posthog=([^;]+)/)

      if (postHogCookieMatch && postHogCookieMatch[1]) {
        try {
          const decodedCookie = decodeURIComponent(postHogCookieMatch[1])
          const postHogData = JSON.parse(decodedCookie)
          distinctId = postHogData.distinct_id
        } catch (e) {
          console.error('Error parsing PostHog cookie:', e)
        }
      }
    }

    await posthog.captureException(err, distinctId || undefined)
  }
}
`
