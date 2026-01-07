import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const NextJSInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, Tab, dedent, snippets } = useMDXComponents()

    const JSEventCapture = snippets?.JSEventCapture

    return (
        <Steps>
            <Step title="Install the package" badge="required">
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
            </Step>

            <Step title="Add environment variables" badge="required">
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
            </Step>

            <Step title="Initialize PostHog" badge="required">
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
                                                  person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users too
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
                                                  person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users too
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

                <CalloutBox type="fyi" title="defaults option">
                    <Markdown>
                        The `defaults` option automatically configures PostHog with recommended settings for new
                        projects. See [SDK defaults](https://posthog.com/docs/libraries/js#sdk-defaults) for details.
                    </Markdown>
                </CalloutBox>
            </Step>

            <Step title="Send events">{JSEventCapture && <JSEventCapture />}</Step>
        </Steps>
    )
}
