import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getWebSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, Tab, dedent, snippets } = ctx

    const JSEventCapture = snippets?.JSEventCapture

    return [
        {
            title: 'Choose an installation method',
            badge: 'required',
            content: (
                <>
                    <Markdown>
                        You can either add the JavaScript snippet directly to your HTML or install the JavaScript SDK
                        via your package manager.
                    </Markdown>

                    <Tab.Group tabs={['HTML snippet', 'JavaScript SDK']}>
                        <Tab.List>
                            <Tab>HTML snippet</Tab>
                            <Tab>JavaScript SDK</Tab>
                        </Tab.List>
                        <Tab.Panels>
                            <Tab.Panel>
                                <Markdown>
                                    Add this snippet to your website within the `&lt;head&gt;` tag. This can also be
                                    used in services like Google Tag Manager:
                                </Markdown>
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'html',
                                            file: 'HTML',
                                            code: dedent`
                                                <script>
                                                    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
                                                    posthog.init('<ph_project_token>', {
                                                        api_host: '<ph_client_api_host>',
                                                        defaults: '2026-01-30'
                                                    })
                                                </script>
                                            `,
                                        },
                                    ]}
                                />
                            </Tab.Panel>
                            <Tab.Panel>
                                <Markdown>
                                    {dedent`
                                        Install the PostHog JavaScript library using your package manager.
                                        Then, import and initialize the PostHog library with your project token and host:
                                    `}
                                </Markdown>
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
                                <CodeBlock
                                    blocks={[
                                        {
                                            language: 'javascript',
                                            file: 'JavaScript',
                                            code: dedent`
                                                import posthog from 'posthog-js'

                                                posthog.init('<ph_project_token>', {
                                                    api_host: '<ph_client_api_host>',
                                                    defaults: '2026-01-30'
                                                })
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
            title: 'Send events',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Once installed, PostHog will automatically start capturing events. You can also manually send
                        events to test your integration:
                    </Markdown>
                    {JSEventCapture && <JSEventCapture />}
                </>
            ),
        },
    ]
}

export const WebInstallation = createInstallation(getWebSteps)
