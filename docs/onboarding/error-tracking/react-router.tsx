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
                        In framework mode, loaders, actions, middleware and server rendering run on your server, and their errors never reach the browser: React Router sends the browser "Unexpected Server Error" instead. Install \`posthog-node\` 6.1.0 or later, create one client for the server process, and create the React Router error handler from it.

                        \`enableExceptionAutocapture\` captures errors no request handles, such as a rejected promise nobody awaits, from the moment the client exists: create it when the module loads, not on first use. \`readPostHogCookie\` links page loads, which carry only the PostHog cookie, to the visitor's person and session replay.
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
                                import { createReactRouterErrorHandler, PostHog } from 'posthog-node'

                                export const posthog = new PostHog('<ph_project_token>', {
                                  host: '<ph_client_api_host>',
                                  enableExceptionAutocapture: true,
                                  readPostHogCookie: true,
                                })

                                export const handleError = createReactRouterErrorHandler(posthog)
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        The handler links each server error to the visitor's person, session and page. It reads IDs you set with \`posthog.withContext\` first, then the \`X-POSTHOG-*\` headers posthog-js adds with \`tracing_headers\`, then the cookie. An anonymous visitor's errors carry their anonymous distinct ID and create no person profile.

                        If visitors can opt out of tracking, set \`opt_out_capturing_persistence_type: 'cookie'\` in \`posthog.init\`, so the server can see the choice: posthog-js stores it in localStorage by default. If you use \`opt_out_capturing_by_default\`, pass \`readPostHogCookie: { optOutCapturingByDefault: true }\`.

                        On Vercel, Netlify or another serverless host, the function can stop as soon as the response is sent. Pass the platform's \`waitUntil\` so queued events are still sent, for example \`waitUntil\` from \`@vercel/functions\`: \`new PostHog('<ph_project_token>', { host: '<ph_client_api_host>', readPostHogCookie: true, waitUntil })\`. On Cloudflare Workers, create the client and the handler for each request, with the request's \`ctx.waitUntil\`, as the [Cloudflare Workers guide](https://posthog.com/docs/libraries/cloudflare-workers) shows.
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
                        Export the handler as \`handleError\` from \`app/entry.server.tsx\` (run \`npx react-router reveal entry.server\` if your app does not have this file yet). React Router calls it for errors in loaders, actions, middleware, resource routes and server rendering, on both page loads and data requests. It skips requests the browser cancelled and the 404 and 405 responses React Router creates, and logs each error the way React Router does.

                        Errors thrown while streaming, after the first part of the page was sent, skip \`handleError\` and reach React's \`onError\` in the same file instead. Call the handler there too, in the \`renderToPipeableStream\` options (\`renderToReadableStream\` on edge runtimes):
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/entry.server.tsx',
                            code: dedent`
                                import { handleError } from './lib/posthog.server'

                                export { handleError }

                                // In handleRequest, in the renderToPipeableStream options:
                                onError(error: unknown) {
                                  responseStatusCode = 500
                                  if (shellRendered) {
                                    void handleError(error, { request })
                                  }
                                },
                            `,
                        },
                    ]}
                />
                <Markdown>
                    {dedent`
                        The handler captures each error once per request, however many hooks pass it on. To keep your own error logging, pass it as an option: \`createReactRouterErrorHandler(posthog, { handleError: yourHandleError })\`. To skip errors you do not want to track, pass \`shouldCapture\`, a function that returns \`false\` for them.

                        React Router does not call \`handleError\` for a promise that a loader returns and the page renders with \`<Await>\`, and the browser receives it as "Unexpected Server Error", which the browser step skips. Pass those rejections to the handler in the loader, and give the \`<Await>\` an \`errorElement\`:
                    `}
                </Markdown>
                <CodeBlock
                    blocks={[
                        {
                            language: 'typescript',
                            file: 'app/routes/product.tsx',
                            code: dedent`
                                import { handleError } from '~/lib/posthog.server'
                                import type { Route } from './+types/product'

                                export async function loader({ params, request }: Route.LoaderArgs) {
                                  const reviews = getReviews(params.id).catch((error) => {
                                    void handleError(error, { request })
                                    throw error
                                  })
                                  return { reviews }
                                }
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

    return [...installSteps, browserStep, serverClientStep, serverErrorsStep, verifyStep]
}

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
