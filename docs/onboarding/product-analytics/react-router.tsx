import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getReactRouterSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent, snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Install the package',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Install the PostHog JavaScript library and React SDK using your package manager:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'npm',
                                code: dedent`
                                    npm install --save posthog-js @posthog/react
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'yarn',
                                code: dedent`
                                    yarn add posthog-js @posthog/react
                                `,
                            },
                            {
                                language: 'bash',
                                file: 'pnpm',
                                code: dedent`
                                    pnpm add posthog-js @posthog/react
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Configure Vite',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Add `posthog-js` and `@posthog/react` to `ssr.noExternal` in your `vite.config.ts` to avoid SSR
                        errors:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'vite.config.ts',
                                code: dedent`
                                    // ... imports

                                    export default defineConfig({
                                      plugins: [tailwindcss(), reactRouter(), tsconfigPaths()],
                                      ssr: {
                                        noExternal: ['posthog-js', '@posthog/react'],
                                      },
                                    });
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Add the PostHogProvider',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Initialize PostHog and wrap your app with the `PostHogProvider` in your `app/entry.client.tsx`
                        file:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'typescript',
                                file: 'app/entry.client.tsx',
                                code: dedent`
                                    import { startTransition, StrictMode } from "react";
                                    import { hydrateRoot } from "react-dom/client";
                                    import { HydratedRouter } from "react-router/dom";
                                    import posthog from "posthog-js";
                                    import { PostHogProvider } from "@posthog/react";

                                    posthog.init("<ph_project_token>", {
                                      api_host: "<ph_client_api_host>",
                                      defaults: "2026-01-30",
                                    });

                                    startTransition(() => {
                                      hydrateRoot(
                                        document,
                                        <PostHogProvider client={posthog}>
                                          <StrictMode>
                                            <HydratedRouter />
                                          </StrictMode>
                                        </PostHogProvider>,
                                      );
                                    });
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Send events',
            badge: undefined,
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const ReactRouterInstallation = createInstallation(getReactRouterSteps)
