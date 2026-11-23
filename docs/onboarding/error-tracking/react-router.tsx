import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { SDK_DEFAULTS_DATE } from '../product-analytics/_snippets/sdkDefaults'
import { getReactRouterInstallSteps } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getReactRouterInstallSteps(ctx).filter((step) => step.title !== 'Add the PostHogProvider')

    const browserStep: StepDefinition = {
        title: 'Capture browser exceptions',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        React Router catches every error thrown while rendering a route or running a loader, action or fetcher, and shows the route's \`ErrorBoundary\`, so these errors never reach the browser's global error handlers. Turn on exception autocapture with \`capture_exceptions: true\` for everything else, and pass an \`onError\` handler to the router for the errors it catches.

                        \`onError\` also receives responses you throw on purpose (\`throw data(..., { status: 404 })\`, unknown URLs) and the browser's copy of a server error, which React Router renames to "Unexpected Server Error" and which the server captures with its full stack. Skip both.

                        In framework mode, the router is \`<HydratedRouter>\` in \`app/entry.client.tsx\` (run \`npx react-router reveal entry.client\` if your app does not have this file yet):
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/entry.client.tsx',
                            code: dedent`
                                import { startTransition, StrictMode } from 'react'
                                import { hydrateRoot } from 'react-dom/client'
                                import { isRouteErrorResponse, type ClientOnErrorFunction } from 'react-router'
                                import { HydratedRouter } from 'react-router/dom'
                                import posthog from 'posthog-js'
                                import { PostHogProvider } from '@posthog/react'

                                posthog.init('<ph_project_token>', {
                                  api_host: '<ph_client_api_host>',
                                  defaults: '${SDK_DEFAULTS_DATE}',
                                  capture_exceptions: true,
                                })

                                const onError: ClientOnErrorFunction = (error) => {
                                  if (isRouteErrorResponse(error)) return
                                  if (error instanceof Error && error.message === 'Unexpected Server Error') return
                                  posthog.captureException(error)
                                }

                                startTransition(() => {
                                  hydrateRoot(
                                    document,
                                    <PostHogProvider client={posthog}>
                                      <StrictMode>
                                        <HydratedRouter onError={onError} />
                                      </StrictMode>
                                    </PostHogProvider>
                                  )
                                })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        In data mode, pass the same handler to \`<RouterProvider router={router} onError={onError} />\`. \`onError\` needs React Router 7.11 or later; on older versions, capture in your root \`ErrorBoundary\` inside a \`useEffect\` with the same two checks. Do not capture in an \`ErrorBoundary\` as well as in \`onError\`: each error would arrive twice. A \`PostHogErrorBoundary\` around the router never sees these errors, because React Router's own boundaries catch them first.
                    `}
                </Markdown>
            </>
        ),
    }

    const serverClientStep: StepDefinition = {
        title: 'Create the server client',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        In framework mode, loaders, actions, middleware and server rendering run on your server, and their errors never reach the browser: React Router sends the browser "Unexpected Server Error" instead. Install \`posthog-node\` and create one client for the server process. \`enableExceptionAutocapture\` captures errors no request handles, such as a rejected promise nobody awaits.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        { language: 'bash', file: 'npm', code: 'npm install posthog-node' },
                        { language: 'bash', file: 'yarn', code: 'yarn add posthog-node' },
                        { language: 'bash', file: 'pnpm', code: 'pnpm add posthog-node' },
                    ]}
                />
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/lib/posthog.server.ts',
                            code: dedent`
                                import { PostHog } from 'posthog-node'

                                export const posthog = new PostHog(process.env.POSTHOG_PROJECT_TOKEN!, {
                                  host: process.env.POSTHOG_HOST,
                                  enableExceptionAutocapture: true,
                                })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Set \`POSTHOG_PROJECT_TOKEN\` and \`POSTHOG_HOST\` where the server runs. \`react-router-serve\` does not read \`.env\` files, and Vite does not replace \`process.env\` in the server build.

                        The snippets on this page need \`posthog-node\` 6 or later. If your app pins \`posthog-node\` 5, call \`posthog.captureException(error, distinctId, properties)\` with the two values instead: in version 5 the second argument is the distinct ID.
                    `}
                </Markdown>
            </>
        ),
    }

    const requestContextStep: StepDefinition = {
        title: 'Link server errors to the user',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        A server exception links to the person and session replay that caused it only when it carries the browser's distinct ID and session ID. Page loads and React Router's data requests send the PostHog cookie; API clients configured with \`tracing_headers\` send \`X-POSTHOG-DISTINCT-ID\` and \`X-POSTHOG-SESSION-ID\`. Read the headers first, then the cookie, and drop a session that has expired:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/lib/posthog-request.server.ts',
                            code: dedent`
                                const SESSION_IDLE_MS = 30 * 60 * 1000
                                const SESSION_MAX_MS = 24 * 60 * 60 * 1000

                                function fromCookie(request: Request): { distinctId?: string; sessionId?: string } {
                                  const match = request.headers.get('cookie')?.match(/(?:^|;\\s*)ph_[^=]+_posthog=([^;]+)/)
                                  if (!match) return {}
                                  try {
                                    const state = JSON.parse(decodeURIComponent(match[1]))
                                    const [lastActivity, sessionId, sessionStart] = state.$sesid ?? []
                                    const now = Date.now()
                                    const active = now - lastActivity < SESSION_IDLE_MS && now - sessionStart < SESSION_MAX_MS
                                    return { distinctId: state.distinct_id, sessionId: active ? sessionId : undefined }
                                  } catch {
                                    return {}
                                  }
                                }

                                // Analytics context only: never use these IDs to authorize anything.
                                export function posthogRequestContext(request: Request) {
                                  const header = (name: string) => request.headers.get(name)?.trim() || undefined
                                  const cookie = fromCookie(request)
                                  const distinctId = header('x-posthog-distinct-id') ?? cookie.distinctId
                                  const url = new URL(request.url)
                                  return {
                                    distinctId: distinctId === '$posthog_cookieless' ? undefined : distinctId,
                                    properties: {
                                      $session_id: header('x-posthog-session-id') ?? cookie.sessionId,
                                      $current_url: url.origin + url.pathname,
                                      $request_method: request.method,
                                      $request_path: url.pathname,
                                      $user_agent: request.headers.get('user-agent') ?? undefined,
                                    },
                                  }
                                }
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const serverErrorsStep: StepDefinition = {
        title: 'Capture server errors',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        Export \`handleError\` from \`app/entry.server.tsx\` (run \`npx react-router reveal entry.server\` if your app does not have this file yet). React Router calls it for errors in loaders, actions, middleware, resource routes and server rendering, on both page loads and data requests. It also calls it for requests the browser cancelled and for the 404 and 405 responses it creates itself: skip those.

                        Errors thrown while streaming, after the first part of the page was sent, skip \`handleError\` and reach React's \`onError\` in the same file instead. Capture there too, once \`shellRendered\` is set:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/entry.server.tsx',
                            code: dedent`
                                import { isRouteErrorResponse, type HandleErrorFunction } from 'react-router'
                                import { posthog } from './lib/posthog.server'
                                import { posthogRequestContext } from './lib/posthog-request.server'

                                export const handleError: HandleErrorFunction = (error, { request }) => {
                                  if (request.signal.aborted || isRouteErrorResponse(error)) return
                                  posthog.captureException(error, posthogRequestContext(request))
                                  console.error(error)
                                }

                                // In handleRequest, in the renderToPipeableStream options:
                                //   onError(error) {
                                //     responseStatusCode = 500
                                //     if (shellRendered && !request.signal.aborted) {
                                //       posthog.captureException(error, posthogRequestContext(request))
                                //       console.error(error)
                                //     }
                                //   },
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        In React Router 7, \`handleError\` works without the \`v8_middleware\` flag. If you deploy to a serverless or edge runtime, use \`posthog-node/edge\` there and \`await posthog.flush()\` before the request ends.
                    `}
                </Markdown>
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Test a server error',
        badge: 'recommended',
        content: (
            <Markdown>
                {dedent`
                    Throw an error from a loader and open that page in a production build (\`npm run build && npm start\`). One exception should arrive from \`posthog-node\` with the page's URL and your browser's session, and none from the browser for the same error.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/events)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, browserStep, serverClientStep, requestContextStep, serverErrorsStep, verifyStep]
}

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
