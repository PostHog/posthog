import {
    OnboardingComponentsContext,
    createInstallation,
} from 'scenes/settings/environment/OnboardingDocsContentWrapper'

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
                        PostHog can automatically capture unhandled exceptions in your Next.js app using the JavaScript Web SDK. Turn it on with \`capture_exceptions: true\` in your \`posthog.init\` call:
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
                                    Also add the capture to a [Global Error component](https://nextjs.org/docs/app/building-your-application/routing/error-handling#handling-global-errors) at \`app/global-error.tsx\`, and create one if your app has none: it catches errors in the root layout and in the first render, before autocapture loads.
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

                        First, install \`@posthog/next\` 0.11.0+ and \`posthog-node\` 5.61.1+, and upgrade \`posthog-js\` to 1.445.1+ if yours is older:
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
                        Then create a \`lib/posthog-server.js\` file that initializes PostHog from \`posthog-node\`. With \`enableExceptionAutocapture\`, it captures uncaught exceptions and unhandled promise rejections. Turn it on for the Node.js runtime only: the edge runtime cannot register process listeners, so the client would fail to start there.

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
                                    // Uncaught exceptions and unhandled promise rejections, on the Node.js runtime only
                                    enableExceptionAutocapture: process.env.NEXT_RUNTIME === 'nodejs',
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
                        To capture errors that occur in your server-side code, set up an [\`instrumentation.ts\`](https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation) file at the root of your project (or in \`src/\`). Next.js calls its \`onRequestError\` hook when a Server Component, Route Handler, or Server Action throws. [\`createOnRequestError\`](https://posthog.com/docs/libraries/next-js/posthog-next) returns that hook, and links each error to the user and session. \`register()\` starts the \`posthog-node\` client when the server starts.

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
                        \`onRequestError\` misses errors thrown in \`proxy.ts\` and in Node.js middleware. If your app has either, wrap it with \`withPostHogProxy\`:
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
                        Errors thrown in \`after()\` callbacks do not reach \`onRequestError\` either. If your app imports \`after\` from \`next/server\`, capture inside each callback:
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
                        **Next.js 14 and earlier** run \`instrumentation.js\` only with the \`instrumentationHook\` flag. They never call \`onRequestError\`, so leave it out, and upgrade to capture Server Component, Route Handler and Server Action errors:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'next.config.js',
                            code: dedent`
                                module.exports = {
                                  // Only on Next.js 14 and earlier: later versions run instrumentation.js without it
                                  experimental: { instrumentationHook: true },
                                }
                            `,
                        },
                    ]}
                />
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
