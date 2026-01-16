import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getReactSteps = (
    CodeBlock: any,
    Markdown: any,
    CalloutBox: any,
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
                        Add your PostHog API key and host to your environment variables. For Vite-based React apps, use the
                        `VITE_PUBLIC_` prefix:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: '.env',
                                code: dedent`
                                    VITE_PUBLIC_POSTHOG_KEY=<ph_project_api_key>
                                    VITE_PUBLIC_POSTHOG_HOST=<ph_client_api_host>
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
                    <Markdown>
                        Wrap your app with the `PostHogProvider` component at the root of your application (such as
                        `main.tsx` if you're using Vite):
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'main.tsx',
                                code: dedent`
                                    import { StrictMode } from 'react'
                                    import { createRoot } from 'react-dom/client'
                                    import './index.css'
                                    import App from './App.jsx'
                                    import { PostHogProvider } from 'posthog-js/react'

                                    const options = {
                                      api_host: import.meta.env.VITE_PUBLIC_POSTHOG_HOST,
                                      defaults: '2025-11-30',
                                    } as const

                                    createRoot(document.getElementById('root')).render(
                                      <StrictMode>
                                        <PostHogProvider apiKey={import.meta.env.VITE_PUBLIC_POSTHOG_KEY} options={options}>
                                          <App />
                                        </PostHogProvider>
                                      </StrictMode>
                                    )
                                `,
                            },
                        ]}
                    />
                    <CalloutBox type="fyi" title="defaults option">
                        <Markdown>
                            The `defaults` option automatically configures PostHog with recommended settings for new
                            projects. See [SDK defaults](https://posthog.com/docs/libraries/js#sdk-defaults) for details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Accessing PostHog in your code',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Use the `usePostHog` hook to access the PostHog instance in any component wrapped by
                        `PostHogProvider`:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'MyComponent.tsx',
                                code: dedent`
                                    import { usePostHog } from 'posthog-js/react'

                                    function MyComponent() {
                                        const posthog = usePostHog()

                                        function handleClick() {
                                            posthog.capture('button_clicked', { button_name: 'signup' })
                                        }

                                        return <button onClick={handleClick}>Sign up</button>
                                    }
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        You can also import `posthog` directly for non-React code or utility functions:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'tsx',
                                file: 'utils/analytics.ts',
                                code: dedent`
                                    import posthog from 'posthog-js'

                                    export function trackPurchase(amount: number) {
                                        posthog.capture('purchase_completed', { amount })
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            badge: 'recommended',
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const ReactInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()
    const steps = getReactSteps(CodeBlock, Markdown, CalloutBox, dedent, snippets)

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
