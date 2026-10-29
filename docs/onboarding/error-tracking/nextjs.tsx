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
                                    You can also create a [Global Error component](https://nextjs.org/docs/app/building-your-application/routing/error-handling#handling-global-errors) in your root layout to capture unhandled exceptions in your root layout. A custom \`global-error.tsx\` replaces the default root boundary, so errors it catches reach PostHog only through its own capture. It also captures render errors that happen before exception autocapture has loaded. Before Next.js 15.2, every client render error is caught by a boundary, so capture in \`global-error.tsx\` as well as in each \`error.tsx\`.
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
                        Next.js enables you to both server-side render pages and add server-side functionality. To integrate PostHog into your Next.js app on the server-side, you can use the [Node SDK](https://posthog.com/docs/libraries/node).

                        First, install the \`posthog-node\` library:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        { language: 'bash', file: 'npm', code: dedent`npm install posthog-node --save` },
                        { language: 'bash', file: 'yarn', code: dedent`yarn add posthog-node` },
                        { language: 'bash', file: 'pnpm', code: dedent`pnpm add posthog-node` },
                        { language: 'bash', file: 'bun', code: dedent`bun add posthog-node` },
                    ]}
                />
                <Markdown>
                    {dedent`
                        For the backend, we can create a \`lib/posthog-server.js\` file. In it, initialize PostHog from \`posthog-node\` as a singleton with your project token and host from [your project settings](https://app.posthog.com/settings/project).

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

                                // Next.js bundles instrumentation.js, proxy.js and each route separately, so a module-level
                                // singleton would create one client per bundle. Keep one per process on globalThis instead.
                                export function getPostHogServer() {
                                  globalThis.__posthogServer ??= new PostHog(
                                    process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN,
                                    {
                                      host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                      flushAt: 1,
                                      flushInterval: 0,
                                      // Captures uncaught exceptions on the Node.js server (there is no process to listen to on the edge)
                                      enableExceptionAutocapture: process.env.NEXT_RUNTIME === 'nodejs',
                                    }
                                  )
                                  return globalThis.__posthogServer
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        You can now use the \`getPostHogServer\` function to capture exceptions in server-side code.
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
                                    throw new Error("This is a test exception for error tracking")
                                } catch (error) {
                                    posthog.captureException(error, {
                                        source: 'test',
                                        user_id: 'test-user-123',
                                    })
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
                        To capture errors that occur in your server-side code, you can set up an [\`instrumentation.ts\`](https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation) file at the root of your project. On Next.js 15 and later, it provides an \`onRequestError\` hook that Next.js calls when a Server Component, Route Handler, Server Action, or middleware throws, in both the Node.js and the edge runtime.

                        Importantly, you need to:

                        1. Set up a \`posthog-node\` client in your server-side code, and create it in \`register()\` so uncaught exceptions are captured from the moment the server starts. See our doc on [setting up Next.js server-side analytics](https://posthog.com/docs/libraries/next-js#server-side-analytics) for more.
                        2. Capture in both runtimes: \`posthog-node\` loads its edge build in the edge runtime. Use \`captureExceptionImmediate\` so the event is sent before the request ends.
                        3. Link the error to the user and their session: read the \`X-POSTHOG-DISTINCT-ID\` and \`X-POSTHOG-SESSION-ID\` headers that \`tracing_headers\` adds first, then the PostHog cookie. Use these values for analytics only, never to authenticate a user.

                        This looks like this:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'instrumentation.js',
                            code: dedent`
                                import { getPostHogServer } from './lib/posthog-server'

                                export function register() {
                                  getPostHogServer()
                                }

                                const SESSION_IDLE_MS = 30 * 60 * 1000
                                const SESSION_MAX_MS = 24 * 60 * 60 * 1000

                                // The browser's identity: tracing headers first, then the PostHog cookie
                                function getIdentity(headers) {
                                  const header = (name) => (Array.isArray(headers[name]) ? headers[name].join('; ') : headers[name])
                                  let distinctId = header('x-posthog-distinct-id')
                                  let sessionId = header('x-posthog-session-id')
                                  const cookieName = \`ph_\${process.env.NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN}_posthog=\`
                                  const cookie = header('cookie')?.split('; ').find((c) => c.startsWith(cookieName))
                                  if (cookie) {
                                    try {
                                      const data = JSON.parse(decodeURIComponent(cookie.slice(cookieName.length)))
                                      distinctId ??= data.distinct_id
                                      // $sesid is [last activity, session ID, session start]
                                      const [lastActivity, id, start] = data.$sesid ?? []
                                      const now = Date.now()
                                      if (!sessionId && id && now - lastActivity < SESSION_IDLE_MS && now - start < SESSION_MAX_MS) {
                                        sessionId = id
                                      }
                                    } catch (e) {
                                      // A malformed cookie leaves the error without a user
                                    }
                                  }
                                  return { distinctId, sessionId }
                                }

                                export const onRequestError = async (err, request, context) => {
                                  const { distinctId, sessionId } = getIdentity(request.headers)
                                  const path = request.path.split('?')[0]
                                  await getPostHogServer().captureExceptionImmediate(err, distinctId, {
                                    $session_id: sessionId,
                                    $current_url: \`https://\${request.headers.host}\${path}\`,
                                    $request_method: request.method,
                                    $request_path: path,
                                    nextjs_route_type: context.routeType,
                                    nextjs_route_path: context.routePath,
                                  })
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        A few errors never reach \`onRequestError\`:

                        - **Functions passed to \`after()\`**: Next.js logs their errors and moves on. Capture inside the callback: wrap its body in \`try\`/\`catch\`, \`await getPostHogServer().captureExceptionImmediate(error)\`, and rethrow.
                        - **\`proxy.ts\` on Next.js 16**: Next.js does not call \`onRequestError\` for errors thrown in the proxy. Wrap the proxy body the same way.
                        - **Next.js 14 and earlier**: there is no \`onRequestError\`, and \`instrumentation.ts\` runs only with \`experimental: { instrumentationHook: true }\` in \`next.config.js\`. Upgrade to Next.js 15, or capture in your route handlers and server actions with \`getPostHogServer().captureException(error)\`.
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
