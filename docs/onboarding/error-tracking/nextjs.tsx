import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { getNextJSClientSteps } from '../product-analytics/nextjs'
import { StepDefinition } from '../steps'

export const getNextJSSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Tab, dedent } = ctx

    const clientSteps = getNextJSClientSteps(ctx)

    const captureClientExceptionsStep: StepDefinition = {
        title: 'Capture client-side exceptions',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        PostHog can automatically capture unhandled exceptions in your Next.js app using the JavaScript Web SDK. Turn it on with \`capture_exceptions: true\` in your \`posthog.init\` call, and add \`tracing_headers\` so requests to your own server carry the user's identity to the server-side capture below:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'instrumentation-client.js',
                            code: dedent`
                                posthog.init(process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN, {
                                  api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                  capture_exceptions: true,
                                  // Sends X-POSTHOG-DISTINCT-ID and X-POSTHOG-SESSION-ID with requests to these hostnames
                                  tracing_headers: [window.location.hostname],
                                })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        It is also possible to manually capture exceptions using the \`captureException\` method:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'JavaScript',
                            code: dedent`
                                posthog.captureException(error, additionalProperties)
                            `,
                        },
                    ]}
                />
                Manual capture is very useful if you already use error boundaries to handle errors in your app:
                <Tab.Group tabs={['App router', 'Pages router']}>
                    <Tab.List>
                        <Tab>App router</Tab>
                        <Tab>Pages router</Tab>
                    </Tab.List>
                    <Tab.Panels>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    Next.js uses [error boundaries](https://nextjs.org/docs/app/building-your-application/routing/error-handling#using-error-boundaries) to handle uncaught exceptions by rendering a fallback UI instead of the crashing components. To set one up, create a \`error.tsx\` file in any of your route directories. This triggers when there is an error rendering your component. An error boundary catches the error before autocapture sees it, so add the capture to **every** \`error.tsx\` your app has. It should look like this:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'typescript',
                                        file: 'error.tsx',
                                        code: dedent`
                                            "use client"
                                            import posthog from "posthog-js"
                                            import { useEffect } from "react"

                                            export default function Error({
                                              error,
                                              reset,
                                            }: {
                                              error: Error & { digest?: string }
                                              reset: () => void
                                            }) {
                                              useEffect(() => {
                                                posthog.captureException(error)
                                              }, [error])
                                              return (
                                                ...
                                              )
                                            }
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    Also create a [Global Error component](https://nextjs.org/docs/app/building-your-application/routing/error-handling#handling-global-errors) at \`app/global-error.tsx\`, or add the capture to the one your app already has. Exception autocapture loads after the page starts, so a render error during the first render reaches PostHog only through this capture. A custom \`global-error.tsx\` also replaces the default root boundary, so the errors it catches reach PostHog only through its own capture.
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'typescript',
                                        file: 'app/global-error.tsx',
                                        code: dedent`
                                            'use client'
                                            import posthog from "posthog-js"
                                            import NextError from "next/error"
                                            import { useEffect } from "react"

                                            export default function GlobalError({
                                              error,
                                              reset,
                                            }: {
                                              error: Error & { digest?: string }
                                              reset: () => void
                                            }) {
                                              useEffect(() => {
                                                posthog.captureException(error)
                                              }, [error])
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
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                        <Tab.Panel>
                            <Markdown>
                                {dedent`
                                    For Pages Router, you can use React's [Error Boundaries](https://react.dev/reference/react/Component#catching-rendering-errors-with-an-error-boundary) to catch JavaScript errors anywhere in the component tree. Create a custom error boundary component and report errors to PostHog in the \`componentDidCatch\` method:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'typescript',
                                        file: 'components/ErrorBoundary.tsx',
                                        code: dedent`
                                            componentDidCatch(error, errorInfo) {
                                              posthog.captureException(error)
                                            }
                                        `,
                                    },
                                ]}
                            />
                            <Markdown>
                                {dedent`
                                    Then wrap your app or specific components with the error boundary:
                                `}
                            </Markdown>
                            <CodeBlock
                                blocks={[
                                    {
                                        language: 'typescript',
                                        file: 'pages/_app.tsx',
                                        code: dedent`
                                            import type { AppProps } from 'next/app'
                                            import ErrorBoundary from '../components/ErrorBoundary'

                                            export default function App({ Component, pageProps }: AppProps) {
                                              return (
                                                <ErrorBoundary>
                                                  <Component {...pageProps} />
                                                </ErrorBoundary>
                                              )
                                            }
                                        `,
                                    },
                                ]}
                            />
                        </Tab.Panel>
                    </Tab.Panels>
                </Tab.Group>
            </>
        ),
    }

    const verifyClientStep: StepDefinition = {
        title: 'Verify error tracking',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    Check that exception events appear in the [activity feed](https://app.posthog.com/activity/events).
                `}
            </Markdown>
        ),
    }

    const installServerStep: StepDefinition = {
        title: 'Installing PostHog SDK for server-side',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Next.js enables you to both server-side render pages and add server-side functionality. To capture server-side exceptions, use [\`@posthog/next\`](https://posthog.com/docs/libraries/next-js/posthog-next) for the errors Next.js reports and the [Node SDK](https://posthog.com/docs/libraries/node) for everything else.

                        First, install \`@posthog/next\` (0.11.0 or later) and \`posthog-node\` (5.61.1 or later):
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        { language: 'bash', file: 'npm', code: dedent`npm install @posthog/next posthog-node` },
                        { language: 'bash', file: 'yarn', code: dedent`yarn add @posthog/next posthog-node` },
                        { language: 'bash', file: 'pnpm', code: dedent`pnpm add @posthog/next posthog-node` },
                        { language: 'bash', file: 'bun', code: dedent`bun add @posthog/next posthog-node` },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Then create a \`lib/posthog-server.js\` file. In it, initialize PostHog from \`posthog-node\` with your project token and host from [your project settings](https://app.posthog.com/settings/project). With \`enableExceptionAutocapture\`, it captures uncaught exceptions and unhandled promise rejections on the Node.js server. Next.js bundles \`instrumentation.js\` and each route separately, so this can create more than one client, but \`posthog-node\` shares one set of process listeners between them and captures each error once.

                        This looks like this:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'lib/posthog-server.js',
                            code: dedent`
                                import { PostHog } from 'posthog-node'

                                let posthogServer = null

                                export function getPostHogServer() {
                                  posthogServer ??= new PostHog(process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN, {
                                    host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                    flushAt: 1,
                                    flushInterval: 0,
                                    // Uncaught exceptions and unhandled promise rejections on the Node.js server
                                    enableExceptionAutocapture: true,
                                  })
                                  return posthogServer
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        You can now use the \`getPostHogServer\` function to capture exceptions your server-side code handles itself. Pass the user's distinct ID when you know it:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'JavaScript',
                            code: dedent`
                                const posthog = getPostHogServer()
                                try {
                                  throw new Error('This is a test exception for error tracking')
                                } catch (error) {
                                  posthog.captureException(error, 'user_distinct_id', { source: 'test' })
                                }
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const verifyServerStep: StepDefinition = {
        title: 'Verify server-side exceptions',
        badge: 'recommended',
        checkpoint: true,
        content: (
            <Markdown>
                {dedent`
                    You should also see events and exceptions in PostHog coming from your server-side code in the activity feed.

                    [Check for server events in PostHog](https://app.posthog.com/activity/events)
                `}
            </Markdown>
        ),
    }

    const captureServerExceptionsStep: StepDefinition = {
        title: 'Capturing server-side exceptions',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        To capture errors that occur in your server-side code, set up an [\`instrumentation.ts\`](https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation) file at the root of your project (or in \`src/\`). On Next.js 15 and later, Next.js calls its \`onRequestError\` hook when a Server Component, Route Handler, Server Action, or middleware throws, in both the Node.js and the edge runtime.

                        \`createOnRequestError\` from \`@posthog/next\` returns that hook. It:

                        - Links the error to the user and their session: from the \`X-POSTHOG-DISTINCT-ID\` and \`X-POSTHOG-SESSION-ID\` headers that \`tracing_headers\` adds, otherwise from the PostHog cookie, while that session is still active.
                        - Adds the request URL (without the query string), method, path, and user agent.
                        - Sends the exception before the request ends.

                        \`register()\` creates the \`posthog-node\` client when the server starts, so uncaught exceptions and unhandled promise rejections are captured from boot, including those in work a request starts and does not await.

                        This looks like this:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'instrumentation.js',
                            code: dedent`
                                import { createOnRequestError } from '@posthog/next'
                                import { getPostHogServer } from './lib/posthog-server'

                                export function register() {
                                  if (process.env.NEXT_RUNTIME === 'nodejs') {
                                    getPostHogServer()
                                  }
                                }

                                export const onRequestError = createOnRequestError({
                                  apiKey: process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN,
                                  host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Next.js does not report errors thrown in \`proxy.ts\` (Next.js 16) or in Node.js middleware (Next.js 15) to \`onRequestError\`. If your app has a proxy or middleware, wrap it with \`withPostHogProxy\`. It captures what the function throws, links it to the user the same way, and rethrows it at once, so the response never waits for PostHog. Where Next.js also reports the error, \`onRequestError\` skips it, so each error is captured once.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'proxy.ts',
                            code: dedent`
                                import { NextResponse } from 'next/server'
                                import type { NextRequest } from 'next/server'
                                import { withPostHogProxy } from '@posthog/next'

                                // On Next.js 15 and earlier, this is middleware.ts with \`export const middleware\`
                                export const proxy = withPostHogProxy(
                                  async (request: NextRequest) => {
                                    // Your existing proxy code
                                    return NextResponse.next()
                                  },
                                  {
                                    apiKey: process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN,
                                    host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                  }
                                )
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Errors thrown in functions passed to \`after()\` never reach \`onRequestError\` either: Next.js logs them and moves on. If your app imports \`after\` from \`next/server\`, capture inside each callback:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/api/orders/route.ts',
                            code: dedent`
                                import { after } from 'next/server'
                                import { getPostHogServer } from '@/lib/posthog-server'

                                after(async () => {
                                  try {
                                    await sendReceipt(order)
                                  } catch (error) {
                                    await getPostHogServer().captureExceptionImmediate(error)
                                    throw error
                                  }
                                })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        On **Next.js 14 and earlier** there is no \`onRequestError\`, and \`instrumentation.ts\` runs only with \`experimental: { instrumentationHook: true }\` in \`next.config.js\`. Upgrade to Next.js 15, or capture in your route handlers and server actions with \`getPostHogServer().captureException(error)\`. \`withPostHogProxy\` works for middleware on these versions too.
                    `}
                </Markdown>
                <Markdown>
                    {dedent`
                        You can find a full example of both this and client-side error tracking in our [Next.js error monitoring tutorial](https://posthog.com/tutorials/nextjs-error-monitoring).
                    `}
                </Markdown>
            </>
        ),
    }

    return [
        ...clientSteps,
        captureClientExceptionsStep,
        verifyClientStep,
        installServerStep,
        verifyServerStep,
        captureServerExceptionsStep,
    ]
}

export const NextJSInstallation = createInstallation(getNextJSSteps)
