import { OnboardingComponentsContext, createInstallation } from 'scenes/onboarding/OnboardingDocsContentWrapper'

import { StepDefinition } from '../steps'

export const getRetoolSteps = (ctx: OnboardingComponentsContext): StepDefinition[] => {
    const { CodeBlock, Markdown, CalloutBox, dedent } = ctx

    return [
        {
            title: 'Open custom scripts',
            badge: 'required',
            content: (
                <Markdown>
                    Retool is a platform for building internal tools. In your Retool app, go to **Settings** &gt;
                    **Custom Scripts**.
                </Markdown>
            ),
        },
        {
            title: 'Add the PostHog snippet',
            badge: 'required',
            content: (
                <>
                    <Markdown>Add the following code to the **Head** section:</Markdown>
                    <CodeBlock
                        blocks={[
                            {
                                language: 'html',
                                file: 'Head section',
                                code: dedent`
                                <script>
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
            title: 'Verify installation',
            badge: 'recommended',
            content: (
                <>
                    <Markdown>
                        Save and refresh your app. PostHog will now automatically capture pageviews, clicks, and other
                        events as your app is used.
                    </Markdown>
                    <CalloutBox type="fyi" title="Learn more">
                        <Markdown>
                            See the [Retool integration docs](https://posthog.com/docs/libraries/retool) for more
                            details.
                        </Markdown>
                    </CalloutBox>
                </>
            ),
        },
    ]
}

export const RetoolInstallation = createInstallation(getRetoolSteps)
