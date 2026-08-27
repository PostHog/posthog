import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getVueInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

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
                                      posthog.init('<ph_project_token>', {
                                        api_host: '<ph_client_api_host>',
                                        defaults: '${SDK_DEFAULTS_DATE}'
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
    ]
}

export const getVueEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return {
        title: 'Send events',
        content: <>{JSEventCapture && <JSEventCapture />}</>,
    }
}

export const getVueSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getVueInstallSteps(ctx),
    getVueEventStep(ctx),
]

export const VueInstallation = createInstallation(getVueSteps)
