import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export function ProductAnalyticsWordpressInstructions(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    return (
        <>
            <h3>Install</h3>
            <p>
                Add PostHog to your{' '}
                <Link to="https://wordpress.org/" target="_blank">
                    WordPress
                </Link>{' '}
                site using a plugin or by adding the snippet directly to your theme.
            </p>
            <h4>Option 1: Using a plugin (recommended)</h4>
            <ol className="deprecated-space-y-4">
                <li>
                    Install a header/footer script plugin like{' '}
                    <Link to="https://wordpress.org/plugins/insert-headers-and-footers/" target="_blank">
                        WPCode
                    </Link>{' '}
                    or similar.
                </li>
                <li>Go to the plugin settings and add a new header script.</li>
                <li>
                    Paste the following code:
                    <CodeSnippet language={Language.HTML}>
                        {`<script>
    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="init capture register register_once register_for_session unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group identify setPersonProperties setPersonPropertiesForFlags resetPersonPropertiesForFlags setGroupPropertiesForFlags resetGroupPropertiesForFlags resetGroups onFeatureFlags addFeatureFlagsHandler onSessionId getSurveys getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
    posthog.init('${currentTeam?.api_token}', {
        api_host: '${apiHostOrigin()}',
    })
</script>`}
                    </CodeSnippet>
                </li>
                <li>Save and activate the script.</li>
            </ol>
            <h4>Option 2: Edit theme directly</h4>
            <p>
                Add the same code snippet to your theme's <code>header.php</code> file, just before the closing{' '}
                <code>&lt;/head&gt;</code> tag. Note: this may be overwritten when updating themes.
            </p>
            <p>
                See the{' '}
                <Link
                    to="https://posthog.com/docs/libraries/wordpress"
                    target="_blank"
                    targetBlankIcon
                    disableDocsPanel
                >
                    WordPress integration docs
                </Link>{' '}
                for more details.
            </p>
        </>
    )
}
