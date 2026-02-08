import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

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
                        PostHog can automatically capture unhandled exceptions in your Next.js app using the JavaScript Web SDK.

                        You can enable exception autocapture for the JavaScript Web SDK in the **Error tracking** section of [your project settings](https://us.posthog.com/settings/project-error-tracking#exception-autocapture). 

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
                                    Next.js uses [error boundaries](https://nextjs.org/docs/app/building-your-application/routing/error-handling#using-error-boundaries) to handle uncaught exceptions by rendering a fallback UI instead of the crashing components. To set one up, create a \`error.tsx\` file in any of your route directories. This triggers when there is an error rendering your component and should look like this:
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
                                    You can also create a [Global Error component](https://nextjs.org/docs/app/building-your-application/routing/error-handling#handling-global-errors) in your root layout to capture unhandled exceptions in your root layout.
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
                    Check that exception events appear in the [activity feed](https://app.posthog.com/activity/explore).
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
                        Next.js enables you to both server-side render pages and add server-side functionality. To integrate PostHog into your Next.js app on the server-side, you can use the [Node SDK](/docs/libraries/node.md).

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
                        For the backend, we can create a \`lib/posthog-server.js\` file. In it, initialize PostHog from \`posthog-node\` as a singleton with your project API key and host from [your project settings](https://app.posthog.com/settings/project).

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
                                let posthogInstance = null
                                export function getPostHogServer() {
                                  if (!posthogInstance) {
                                    posthogInstance = new PostHog(
                                      process.env.NEXT_PUBLIC_POSTHOG_KEY,
                                      {
                                        host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                        flushAt: 1,
                                        flushInterval: 0,
                                      }
                                    )
                                  }
                                  return posthogInstance
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

                    [Check for server events in PostHog](https://app.posthog.com/activity/explore)
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
                        To capture errors that occur in your server-side code, you can set up an [\`instrumentation.ts\`](https://nextjs.org/docs/app/building-your-application/optimizing/instrumentation) file at the root of your project. This provides a \`onRequestError\` hook that you can use to capture errors.

                        Importantly, you need to:

                        1. Set up a \`posthog-node\` client in your server-side code. See our doc on [setting up Next.js server-side analytics](/docs/libraries/next-js#server-side-analytics.md) for more.
                        2. Check the request is running in the \`nodejs\` runtime to ensure PostHog works. You can call \`posthog.debug()\` to get verbose logging.
                        3. Get the \`distinct_id\` from the cookie to connect the error to a specific user.

                        This looks like this:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'javascript',
                            file: 'JavaScript',
                            code: dedent`
                                // instrumentation.js
                                export function register() {
                                  // No-op for initialization
                                }
                                export const onRequestError = async (err, request, context) => {
                                  if (process.env.NEXT_RUNTIME === 'nodejs') {
                                    const { getPostHogServer } = require('./lib/posthog-server')
                                    const posthog = getPostHogServer()
                                    let distinctId = null
                                    if (request.headers.cookie) {
                                      // Normalize multiple cookie arrays to string
                                      const cookieString = Array.isArray(request.headers.cookie)
                                        ? request.headers.cookie.join('; ')
                                        : request.headers.cookie
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
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        You can find a full example of both this and client-side error tracking in our [Next.js error monitoring tutorial](/tutorials/nextjs-error-monitoring.md).
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
