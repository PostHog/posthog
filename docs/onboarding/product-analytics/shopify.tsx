import { useMDXComponents } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export const ShopifyInstallation = (): JSX.Element => {
    const { CodeBlock, Markdown, dedent } = useMDXComponents()

    return (
        <>
            <Markdown>
                Add PostHog to your Shopify store to track customer behavior, conversions, and e-commerce events.
            </Markdown>
            <Markdown>
                {`1. In your Shopify admin, go to **Online Store** > **Themes**.
2. Click **Actions** > **Edit code** on your current theme.
3. Open \`theme.liquid\` and paste the following code just before the closing \`</head>\` tag:`}
            </Markdown>
            <CodeBlock
                blocks={[
                    {
                        language: 'html',
                        file: 'theme.liquid',
                        code: dedent`
                            <script>
                                !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
                                posthog.init('<ph_project_api_key>', {
                                    api_host: '<ph_client_api_host>',
                                    defaults: '2025-11-30',
                                    person_profiles: 'identified_only', // or 'always' to create profiles for anonymous users too
                                })
                            </script>
                        `,
                    },
                ]}
            />
            <Markdown>4. Click **Save**.</Markdown>
            <Markdown>
                PostHog will now capture pageviews, clicks, and other events on your Shopify store. See the [Shopify
                integration docs](https://posthog.com/docs/libraries/shopify) for tracking checkout events and revenue.
            </Markdown>
        </>
    )
}
