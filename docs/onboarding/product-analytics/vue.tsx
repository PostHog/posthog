import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getVueSteps = (CodeBlock: any, Markdown: any, CalloutBox: any, dedent: any, snippets: any): StepDefinition[] => {
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
                    <CalloutBox type="fyi" title="Vue version">
                        <Markdown>
                            This guide is for Vue 3 and above. For Vue 2.x, see our [Vue
                            docs](https://posthog.com/docs/libraries/vue-js).
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
        {
            title: 'Create a composable',
            badge: 'required',
            content: (
                <>
                    <Markdown>Create a new file `src/composables/usePostHog.js`:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'src/composables/usePostHog.js',
                                code: dedent`
                                    import posthog from 'posthog-js'

                                    export function usePostHog() {
                                      posthog.init('<ph_project_api_key>', {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '2025-11-30'
                                      })

                                      return { posthog }
                                    }
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Import in your router',
            badge: 'required',
            content: (
                <>
                    <Markdown>In `router/index.js`, import the `usePostHog` composable and call it:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'javascript',
                                file: 'router/index.js',
                                code: dedent`
                                    import { createRouter, createWebHistory } from 'vue-router'
                                    import HomeView from '../views/HomeView.vue'
                                    import { usePostHog } from '@/composables/usePostHog'

                                    const router = createRouter({
                                      history: createWebHistory(import.meta.env.BASE_URL),
                                      routes: [
                                        {
                                          path: '/',
                                          name: 'home',
                                          component: HomeView,
                                        },
                                        {
                                          path: '/about',
                                          name: 'about',
                                          component: () => import('../views/AboutView.vue'),
                                        },
                                      ],
                                    })

                                    const { posthog } = usePostHog()

                                    export default router
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const VueInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, CalloutBox, dedent, snippets } = useMDXComponents()
    const steps = getVueSteps(CodeBlock, Markdown, CalloutBox, dedent, snippets)

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
