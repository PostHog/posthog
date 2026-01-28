import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { WebAnalyticsAllJSFinalSteps } from './FinalSteps'

export function ShopifyInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                Add PostHog to your{' '}
                <Link to="https://www.shopify.com/" target="_blank">
                    Shopify
                </Link>{' '}
                store.
            </p>
            <ol className="deprecated-space-y-4">
                <li>
                    In your Shopify admin, go to <strong>Online Store</strong> → <strong>Themes</strong>.
                </li>
                <li>
                    Click <strong>Actions</strong> → <strong>Edit code</strong>.
                </li>
                <li>
                    Open <code>theme.liquid</code> and paste the following before <code>&lt;/head&gt;</code>:
                    <CodeSnippet language={Language.HTML}>
                        {`<script>
    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
    posthog.init('${currentTeam?.api_token}', {
        api_host: '${apiHostOrigin()}',
    })
</script>`}
                    </CodeSnippet>
                </li>
                <li>Save.</li>
            </ol>
            <WebAnalyticsAllJSFinalSteps />
        </>
    )
}
