import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getNextJSSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
    Tab: any,
    dedent: any,
    snippets: any
): StepDefinition[] => {
    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>Install the PostHog JavaScript library using your package manager:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-js
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-js
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Add environment variables',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Add your PostHog API key and host to your `.env.local` file and to your hosting provider (e.g.
                        Vercel, Netlify). These values need to start with `NEXT_PUBLIC_` to be accessible on the
                        client-side.
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: '.env.local',
                                code: dedent`
                                    NEXT_PUBLIC_POSTHOG_KEY=<ph_project_api_key>
                                    NEXT_PUBLIC_POSTHOG_HOST=<ph_client_api_host>
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Initialize PostHog',
            badge: 'required',
            content: (
                <>
                    <Markdown>Choose the integration method based on your Next.js version and router type.</Markdown>

                    <Tab.Group tabs={['Next.js 15.3+', 'App router', 'Pages router']}>
                        <Tab.List>
                            <Tab>Next.js 15.3+</Tab>
                            <Tab>App router</Tab>
                            <Tab>Pages router</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    If you're using Next.js 15.3+, you can use `instrumentation-client.ts` for a
                                    lightweight, fast integration:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'instrumentation-client.ts',
                                            code: dedent`
                                                import posthog from 'posthog-js'

                                                posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
                                                    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                                    defaults: '2025-11-30'
                                                })
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    For the App router, create a `providers.tsx` file in your `app` folder. The `posthog-js`
                                    library needs to be initialized on the client-side using the `'use client'` directive:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'app/providers.tsx',
                                            code: dedent`
                                                'use client'

                                                import { usePathname, useSearchParams } from "next/navigation"
                                                import { useEffect } from "react"

                                                import posthog from 'posthog-js'
                                                import { PostHogProvider as PHProvider } from 'posthog-js/react'

                                                export function PostHogProvider({ children }: { children: React.ReactNode }) {
                                                  useEffect(() => {
                                                    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY as string, {
                                                      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                                      defaults: '2025-11-30'
                                                    })
                                                  }, [])

                                                  return (
                                                    <PHProvider client={posthog}>
                                                      {children}
                                                    </PHProvider>
                                                  )
                                                }
                                            `,
                                        },
                                    ]}
                                />
                                <Markdown>
                                    Then import the `PostHogProvider` component in your `app/layout.tsx` and wrap your app
                                    with it:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'app/layout.tsx',
                                            code: dedent`
                                                import './globals.css'
                                                import { PostHogProvider } from './providers'

                                                export default function RootLayout({ children }: { children: React.ReactNode }) {
                                                  return (
                                                    <html lang="en">
                                                      <body>
                                                        <PostHogProvider>
                                                          {children}
                                                        </PostHogProvider>
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
                                    For the Pages router, integrate PostHog at the root of your app in `pages/_app.tsx`:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'pages/_app.tsx',
                                            code: dedent`
                                                import { useEffect } from 'react'
                                                import { Router } from 'next/router'
                                                import posthog from 'posthog-js'
                                                import { PostHogProvider } from 'posthog-js/react'
                                                import type { AppProps } from 'next/app'

                                                export default function App({ Component, pageProps }: AppProps) {

                                                  useEffect(() => {
                                                    posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY as string, {
                                                      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
                                                      defaults: '2025-11-30',
                                                      loaded: (posthog) => {
                                                        if (process.env.NODE_ENV === 'development') posthog.debug()
                                                      }
                                                    })
                                                  }, [])

                                                  return (
                                                    <PostHogProvider client={posthog}>
                                                      <Component {...pageProps} />
                                                    </PostHogProvider>
                                                  )
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>

                    <CalloutBox type="fyi" title="Defaults option">
                        <Markdown>
                            The `defaults` option automatically configures PostHog with recommended settings for new
                            projects. See [SDK defaults](https://posthog.com/docs/libraries/js#sdk-defaults) for details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Accessing PostHog on the client',
            badge: 'recommended',
            content: (
                <>
                    <Tab.Group tabs={['Next.js 15.3+', 'App/Pages router']}>
                        <Tab.List>
                            <Tab>Next.js 15.3+</Tab>
                            <Tab>App/Pages router</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    Once initialized in `instrumentation-client.ts`, import `posthog` from `posthog-js`
                                    anywhere and call the methods you need:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'app/checkout/page.tsx',
                                            code: dedent`
                                                'use client'

                                                import posthog from 'posthog-js'

                                                export default function CheckoutPage() {
                                                    function handlePurchase() {
                                                        posthog.capture('purchase_completed', { amount: 99 })
                                                    }

                                                    return <button onClick={handlePurchase}>Complete purchase</button>
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    Use the `usePostHog` hook to access PostHog in client components:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'app/checkout/page.tsx',
                                            code: dedent`
                                                'use client'

                                                import { usePostHog } from 'posthog-js/react'

                                                export default function CheckoutPage() {
                                                    const posthog = usePostHog()

                                                    function handlePurchase() {
                                                        posthog.capture('purchase_completed', { amount: 99 })
                                                    }

                                                    return <button onClick={handlePurchase}>Complete purchase</button>
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
        },
        {
            title: 'Server-side setup',
            badge: 'optional',
            content: (
                <>
                    <Markdown>
                        To capture events from API routes or server actions, install `posthog-node`:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install posthog-node
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-node
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-node
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        Then, initialize PostHog in your API route or server action. Choose the method based on your
                        router type:
                    </Markdown>

                    <Tab.Group tabs={['App router', 'Pages router']}>
                        <Tab.List>
                            <Tab>App router</Tab>
                            <Tab>Pages router</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    For the App router, you can use PostHog in API routes or server actions. Create a new
                                    PostHog client instance for each request, or reuse a singleton instance across
                                    requests:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'app/api/example/route.ts',
                                            code: dedent`
                                                import { PostHog } from 'posthog-node'

                                                export async function POST(request: Request) {
                                                    const posthog = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
                                                        host: process.env.NEXT_PUBLIC_POSTHOG_HOST
                                                    })

                                                    posthog.capture({
                                                        distinctId: 'distinct_id_of_the_user',
                                                        event: 'event_name'
                                                    })

                                                    await posthog.shutdown()
                                                }
                                            `,
                                        },
                                    ]}
                                />
                                <Markdown>
                                    You can also use PostHog in server actions:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'app/actions.ts',
                                            code: dedent`
                                                'use server'

                                                import { PostHog } from 'posthog-node'

                                                export async function myServerAction() {
                                                    const posthog = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
                                                        host: process.env.NEXT_PUBLIC_POSTHOG_HOST
                                                    })

                                                    posthog.capture({
                                                        distinctId: 'distinct_id_of_the_user',
                                                        event: 'server_action_completed'
                                                    })

                                                    await posthog.shutdown()
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    For the Pages router, use PostHog in your API routes:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'typescript',
                                            file: 'pages/api/example.ts',
                                            code: dedent`
                                                import { PostHog } from 'posthog-node'
                                                import type { NextApiRequest, NextApiResponse } from 'next'

                                                export default async function handler(
                                                    req: NextApiRequest,
                                                    res: NextApiResponse
                                                ) {
                                                    const posthog = new PostHog(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
                                                        host: process.env.NEXT_PUBLIC_POSTHOG_HOST
                                                    })

                                                    posthog.capture({
                                                        distinctId: 'distinct_id_of_the_user',
                                                        event: 'event_name'
                                                    })

                                                    await posthog.shutdown()

                                                    res.status(200).json({ success: true })
                                                }
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                        </Tab.Panels>
                    </Tab.Group>

                    <CalloutBox type="fyi" title="Important">
                        <Markdown>
                            Always call `await posthog.shutdown()` when you're done with the client to ensure all events
                            are flushed before the request completes. For better performance, consider creating a
                            singleton PostHog instance that you reuse across requests.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    {JSEventCapture && <JSEventCapture />}
                </>
            ),
        },
    ]
}

export const NextJSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = useMDXComponents()
    const steps = getNextJSSteps(CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets)

    return (
        <Steps>
            {steps.map((step, index) => (
                <Step key={index} title={step.title} badge={step.badge}>
                    {step.content}
                </Step>
            ))}
        </Steps>
    )
}
