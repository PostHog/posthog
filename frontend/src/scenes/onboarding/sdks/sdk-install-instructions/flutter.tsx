import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

function FlutterInstallSnippet(): JSX.Element {
    return <CodeSnippet language={Language.YAML}>posthog_flutter: ^4.0.0</CodeSnippet>
}

function FlutterAndroidSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <CodeSnippet language={Language.XML}>
            {'<application>\n\t<activity>\n\t\t[...]\n\t</activity>\n\t<meta-data android:name="com.posthog.posthog.API_KEY" android:value="' +
                currentTeam?.api_token +
                '" />\n\t<meta-data android:name="com.posthog.posthog.POSTHOG_HOST" android:value="' +
                url +
                '" />\n\t<meta-data android:name="com.posthog.posthog.TRACK_APPLICATION_LIFECYCLE_EVENTS" android:value="true" />\n\t<meta-data android:name="com.posthog.posthog.DEBUG" android:value="true" />\n</application>'}
        </CodeSnippet>
    )
}

function FlutterIOSSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <CodeSnippet language={Language.XML}>
            {'<dict>\n\t[...]\n\t<key>com.posthog.posthog.API_KEY</key>\n\t<string>' +
                currentTeam?.api_token +
                '</string>\n\t<key>com.posthog.posthog.POSTHOG_HOST</key>\n\t<string>' +
                url +
                '</string>\n\t<key>com.posthog.posthog.CAPTURE_APPLICATION_LIFECYCLE_EVENTS</key>\n\t<true/>\n\t[...]\n</dict>'}
        </CodeSnippet>
    )
}

function FlutterWebSetupSnippet(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const url = apiHostOrigin()

    return (
        <CodeSnippet language={Language.HTML}>
            {`<!DOCTYPE html>
<html>
  <head>
    ...
    <script>
      !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
      posthog.init('${currentTeam?.api_token}', {api_host: '${url}'})
    </script>
  </head>

  <body>
    ...
  </body>
</html>`}
        </CodeSnippet>
    )
}

export function SDKInstallFlutterInstructions(): JSX.Element {
    return (
        <>
            <h3>Install</h3>
            <FlutterInstallSnippet />
            <h3>Android Setup</h3>
            <p className="prompt-text">Add these values in AndroidManifest.xml</p>
            <FlutterAndroidSetupSnippet />
            <h3>iOS/macOS Setup</h3>
            <p className="prompt-text">Add these values in Info.plist</p>
            <FlutterIOSSetupSnippet />
            <h3>Web Setup</h3>
            <p className="prompt-text">Add these values in index.html</p>
            <FlutterWebSetupSnippet />
        </>
    )
}
