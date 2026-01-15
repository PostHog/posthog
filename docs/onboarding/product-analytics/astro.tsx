import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'
import { StepDefinition } from '../steps'

export const getAstroSteps = (CodeBlock: any, Markdown: any, dedent: any, snippets: any): StepDefinition[] => {
    const JSEventCapture = snippets?.JSEventCapture

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
                        In this file, add your PostHog web snippet. Be sure to include the `is:inline` directive to prevent
                        Astro from processing it:
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
                                        !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
                                        posthog.init('<ph_project_api_key>', {
                                            api_host: '<ph_client_api_host>',
                                            defaults: '2025-11-30'
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
                        Create a layout where we will use `posthog.astro`. Create a new file `PostHogLayout.astro` in your
                        `src/layouts` folder:
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
        {
            title: 'Send events',
            content: <>{JSEventCapture && <JSEventCapture />}</>,
        },
    ]
}

export const AstroInstallation = (): JSX.Element => {
    const { Steps, Step, CodeBlock, Markdown, dedent, snippets } = useMDXComponents()
    const steps = getAstroSteps(CodeBlock, Markdown, dedent, snippets)

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
