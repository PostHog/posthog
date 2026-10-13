import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/shared/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'
import { DEFAULT_SNIPPET_METHODS, snippetFunctions } from './_snippets/js-snippet-builder'
import { SDK_DEFAULTS_DATE } from './_snippets/sdkDefaults'

export const getAstroInstallSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, dedent } = ctx

    return [
        {
            title: 'Create the PostHog component',
            badge: 'required',
            content: (
                <>
                    <Markdown>In your `src/components` folder, create a `posthog.astro` file:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    cd ./src/components
                                    # or 'cd ./src && mkdir components && cd ./components' if your components folder doesn't exist
                                    touch posthog.astro
                                `,
                            },
                        ]}
                    />
                    <Markdown>
                        In this file, add your PostHog web snippet. Be sure to include the `is:inline` directive to
                        prevent Astro from processing it:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'src/components/posthog.astro',
                                code: dedent`
                                    ---
                                    // src/components/posthog.astro
                                    ---
                                    <script is:inline>
                                        ${snippetFunctions(DEFAULT_SNIPPET_METHODS)}
                                        posthog.init('<ph_project_token>', {
                                            api_host: '<ph_client_api_host>',
                                            defaults: '${SDK_DEFAULTS_DATE}'
                                        })
                                    </script>
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Create a layout',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        Create a layout where we will use `posthog.astro`. Create a new file `PostHogLayout.astro` in
                        your `src/layouts` folder:
                    </Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'bash',
                                file: 'Terminal',
                                code: dedent`
                                    cd ./src/layouts
                                    # or 'cd ./src && mkdir layouts && cd ./layouts' if your layouts folder doesn't exist
                                    touch PostHogLayout.astro
                                `,
                            },
                        ]}
                    />
                    <Markdown>Add the following code to `PostHogLayout.astro`:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'src/layouts/PostHogLayout.astro',
                                code: dedent`
                                    ---
                                    import PostHog from '../components/posthog.astro'
                                    ---
                                    <head>
                                        <PostHog />
                                    </head>
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
        {
            title: 'Use the layout in your pages',
            badge: 'required',
            content: (
                <>
                    <Markdown>Update your pages (like `index.astro`) to wrap your app with the new layout:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'src/pages/index.astro',
                                code: dedent`
                                    ---
                                    import PostHogLayout from '../layouts/PostHogLayout.astro';
                                    ---
                                    <PostHogLayout>
                                      <!-- your existing app components -->
                                    </PostHogLayout>
                                `,
                            },
                        ]}
                    />
                </>
            ),
        },
    ]
}

export const getAstroEventStep = (ctx: OnboardingComponentsContext): StepDefinition => {
    const { snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return {
        title: 'Send events',
        content: <>{JSEventCapture && <JSEventCapture />}</>,
    }
}

export const getAstroSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => [
    ...getAstroInstallSteps(ctx),
    getAstroEventStep(ctx),
]

export const AstroInstallation = createInstallation(getAstroSteps)
