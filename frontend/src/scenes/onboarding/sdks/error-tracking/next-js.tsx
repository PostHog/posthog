import { Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

import { SDKInstallNextJSInstructions } from '../sdk-install-instructions/next-js'
import { JSManualCapture } from './FinalSteps'

export function NextJSInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

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
                Create a{' '}
                <Link
                    target="_blank"
                    to="https://nextjs.org/docs/app/building-your-application/routing/error-handling#handling-global-errors"
                >
                    Global Error component
                </Link>{' '}
                in your root layout to capture unhandled exceptions.
            </p>
            <CodeSnippet language={Language.JavaScript}>{globalErrorComponent}</CodeSnippet>
            <p>
                <code>error.tsx</code> files take precedence over the Global error component. If you use{' '}
                <code>Error</code> components to handle uncaught exceptions at different levels of you route hierarchy
                and want to capture the associated exception, you will need to do so manually:
            </p>
            <CodeSnippet language={Language.JavaScript}>{errorComponent}</CodeSnippet>
            <JSManualCapture />
            <h3>Capturing server errors</h3>
            <p>
                Next.js offers the <code>onRequestError</code> hook in <code>instrumentation.ts</code> to capture errors
                that occur during server-side rendering.
            </p>
            <CodeSnippet language={Language.TypeScript}>
                {instrumentationComponent(currentTeam?.api_token ?? '<API_TOKEN>')}
            </CodeSnippet>
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

const instrumentationComponent = (api_token: string): string => `// instrumentation.ts

import { type Instrumentation } from 'next'
import posthog from "posthog-node";

const client = new PostHog('${api_token}')

export const onRequestError: Instrumentation.onRequestError = async (err) => {
  client.captureException(error);
}
`
