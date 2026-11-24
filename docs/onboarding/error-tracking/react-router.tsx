import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { SDK_DEFAULTS_DATE } from '../product-analytics/_snippets/sdkDefaults'
import { getReactRouterInstallSteps } from '../product-analytics/react-router'
import { StepDefinition } from '../steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    const installSteps = getReactRouterInstallSteps(ctx, { includeProvider: false })

    const browserStep: StepDefinition = {
        title: 'Capture browser exceptions',
        badge: 'required',
        content: (
            <>
                <Markdown>
                    {dedent`
                        React Router catches every error thrown while rendering a route or running a loader, action or fetcher, and shows the route's \`ErrorBoundary\`, so these errors never reach the browser's global error handlers. Turn on exception autocapture with \`capture_exceptions: true\` for everything else, and pass an \`onError\` handler to the router for the errors it catches.

                        \`onError\` also receives responses you throw on purpose (\`throw data(..., { status: 404 })\`, unknown URLs) and, in production builds, the browser's copy of a server error, which React Router renames to "Unexpected Server Error". The server captures the original with its full stack. Skip both.

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
                        Which prop to use depends on your React Router version:

                        - **7.11 or later:** \`onError\`, as above.
                        - **7.8.2 to 7.10:** pass the same handler as \`unstable_onError\` and type it with \`unstable_ClientOnErrorFunction\`.
                        - **Earlier versions:** capture inside a \`useEffect\` in every \`ErrorBoundary\` your routes export, with the same two checks.

                        In data mode, pass the handler to \`<RouterProvider router={router} onError={onError} />\` and skip the server steps below. In declarative mode (\`<BrowserRouter>\`), React Router has no error boundaries of its own: follow the [React guide](https://posthog.com/docs/error-tracking/installation/react) instead.

                        Do not also capture in an \`ErrorBoundary\`: each error would arrive twice. In framework and data mode, a \`PostHogErrorBoundary\` around the router never sees these errors, because React Router's own boundaries catch them first.
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
                        In framework mode, loaders, actions, middleware and server rendering run on your server, and their errors never reach the browser: React Router sends the browser "Unexpected Server Error" instead. Install \`posthog-node\` and create one client for the server process. \`enableExceptionAutocapture\` captures errors no request handles, such as a rejected promise nobody awaits, from the moment the client exists: create it when the module loads, not on first use.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        { language: 'bash', file: 'npm', code: 'npm install posthog-node' },
                        { language: 'bash', file: 'yarn', code: 'yarn add posthog-node' },
                        { language: 'bash', file: 'pnpm', code: 'pnpm add posthog-node' },
                        { language: 'bash', file: 'bun', code: 'bun add posthog-node' },
                    ]}
                />
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/lib/posthog.server.ts',
                            code: dedent`
                                import { PostHog } from 'posthog-node'

                                export const posthog = new PostHog('<ph_project_token>', {
                                  host: '<ph_client_api_host>',
                                  enableExceptionAutocapture: true,
                                })
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        On Vercel, Netlify or another serverless host, the function can stop as soon as the response is sent. Pass the platform's \`waitUntil\` so queued events are still sent, for example \`waitUntil\` from \`@vercel/functions\`: \`new PostHog('<ph_project_token>', { host: '<ph_client_api_host>', waitUntil })\`. On Cloudflare Workers, follow the [Cloudflare Workers guide](https://posthog.com/docs/libraries/cloudflare-workers) to create the client.
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
                        A server exception links to the person and session replay that caused it only when it carries the browser's distinct ID and session ID. API clients configured with \`tracing_headers\` send \`X-POSTHOG-DISTINCT-ID\` and \`X-POSTHOG-SESSION-ID\`. Page loads and React Router's data requests send only the PostHog cookie. Read the headers first, then your project's cookie, and drop a session that has expired:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/lib/posthog-request.server.ts',
                            code: dedent`
                                // posthog-js defaults. Change SESSION_IDLE_MS if you set session_idle_timeout_seconds.
                                const SESSION_IDLE_MS = 30 * 60 * 1000
                                const SESSION_MAX_MS = 24 * 60 * 60 * 1000

                                function readCookie(request: Request, name: string): string | undefined {
                                  for (const part of request.headers.get('cookie')?.split(';') ?? []) {
                                    const [key, ...value] = part.trim().split('=')
                                    if (key === name) return value.join('=')
                                  }
                                }

                                function fromCookie(request: Request): { distinctId?: string; sessionId?: string } {
                                  const raw = readCookie(request, 'ph_<ph_project_token>_posthog')
                                  if (!raw) return {}
                                  try {
                                    const state = JSON.parse(decodeURIComponent(raw))
                                    const [lastActivity, sessionId, sessionStart = lastActivity] = Array.isArray(state.$sesid) ? state.$sesid : []
                                    const now = Date.now()
                                    const active = Math.abs(now - lastActivity) < SESSION_IDLE_MS && Math.abs(now - sessionStart) < SESSION_MAX_MS
                                    return { distinctId: state.distinct_id, sessionId: active ? sessionId : undefined }
                                  } catch {
                                    return {}
                                  }
                                }

                                function visitor(request: Request): { distinctId?: string; $session_id?: string; $user_agent?: string } {
                                  // Visitors who opted out are not linked
                                  if (readCookie(request, '__ph_opt_in_out_<ph_project_token>') === '0') return {}
                                  const header = (name: string) => request.headers.get(name)?.trim() || undefined
                                  const cookie = fromCookie(request)
                                  const distinctId = header('x-posthog-distinct-id') ?? cookie.distinctId
                                  return {
                                    distinctId: distinctId === '$posthog_cookieless' ? undefined : distinctId,
                                    $session_id: header('x-posthog-session-id') ?? cookie.sessionId,
                                    $user_agent: request.headers.get('user-agent') ?? undefined,
                                  }
                                }

                                // For captureException only. Never use these IDs to authorize anything.
                                export function posthogExceptionContext(request: Request) {
                                  const url = new URL(request.url)
                                  // Client navigations request /page.data, and /_root.data (React Router 7) or /_.data (React Router 8)
                                  // for the home page: report the page
                                  const path = url.pathname.replace(/\\/_(root)?\\.data$/, '/').replace(/\\.data$/, '')
                                  const { distinctId, ...properties } = visitor(request)
                                  return {
                                    distinctId,
                                    properties: { ...properties, $current_url: url.origin + path, $request_method: request.method, $request_path: path },
                                  }
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        The distinct ID of an anonymous visitor is included: exceptions never create person profiles, so server errors group with the same visitor's browser errors. If visitors can opt out of tracking, set \`opt_out_capturing_persistence_type: 'cookie'\` in \`posthog.init\`, so the server can see the choice. posthog-js stores it in localStorage by default.
                    `}
                </Markdown>
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
                        Export \`handleError\` from \`app/entry.server.tsx\` (run \`npx react-router reveal entry.server\` if your app does not have this file yet). React Router calls it for errors in loaders, actions, middleware, resource routes and server rendering, on both page loads and data requests. It also calls it for requests the browser cancelled and for the 404 and 405 responses it creates itself: skip those. Exporting \`handleError\` replaces React Router's own error log, so log the error yourself. Add to \`app/entry.server.tsx\`:
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
                                import { posthogExceptionContext } from './lib/posthog-request.server'

                                export const handleError: HandleErrorFunction = (error, { request }) => {
                                  if (request.signal.aborted) return
                                  console.error(error)
                                  if (isRouteErrorResponse(error)) return
                                  posthog.captureException(error, posthogExceptionContext(request))
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        Errors thrown while streaming, after the first part of the page was sent, skip \`handleError\` and reach React's \`onError\` in the same file instead. Capture them there too, in the \`renderToPipeableStream\` options (\`renderToReadableStream\` on edge runtimes):
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/entry.server.tsx',
                            code: dedent`
                                onError(error: unknown) {
                                  responseStatusCode = 500
                                  if (shellRendered && !request.signal.aborted) {
                                    posthog.captureException(error, posthogExceptionContext(request))
                                    console.error(error)
                                  }
                                },
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        React Router does not call \`handleError\` for a promise that a loader returns and the page renders with \`<Await>\`, and the browser receives it as "Unexpected Server Error", which the browser step skips. Capture those rejections in the loader, and give the \`<Await>\` an \`errorElement\`: without one, a rejection during a page load also reaches the stream \`onError\` and arrives twice.
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/routes/product.tsx',
                            code: dedent`
                                import { posthog } from '~/lib/posthog.server'
                                import { posthogExceptionContext } from '~/lib/posthog-request.server'
                                import type { Route } from './+types/product'

                                export async function loader({ params, request }: Route.LoaderArgs) {
                                  const reviews = getReviews(params.id).catch((error) => {
                                    posthog.captureException(error, posthogExceptionContext(request))
                                    throw error
                                  })
                                  return { reviews }
                                }
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        These snippets use the \`posthog-node\` 6 call form. On \`posthog-node\` 5, pass the distinct ID and the properties separately:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'posthog-node 5',
                            code: dedent`
                                const { distinctId, properties } = posthogExceptionContext(request)
                                posthog.captureException(error, distinctId, properties)
                            `,
                        },
                    ]}
                />
            </>
        ),
    }

    const verifyStep: StepDefinition = {
        title: 'Test a server error',
        badge: 'recommended',
        content: (
            <Markdown>
                {dedent`
                    Throw an error from a loader, then run \`npm run build\` and \`npm start\`. Load another page first, so posthog-js sets its cookie, then open the failing page, and also navigate to it from another page. Each should send one exception from \`posthog-node\` with the page's URL and your browser's session, and none from the browser for the same error.

                    Test with a production build: in \`react-router dev\`, React Router sends the browser the original server error, so each error arrives twice.

                    [Check for exceptions in PostHog](https://app.posthog.com/activity/events)
                `}
            </Markdown>
        ),
    }

    return [...installSteps, browserStep, serverClientStep, requestContextStep, serverErrorsStep, verifyStep]
}

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
