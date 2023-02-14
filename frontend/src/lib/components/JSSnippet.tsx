import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useValues } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { useState } from 'react'
import { LemonCheckbox } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconInfo } from 'lib/lemon-ui/icons'

export function JSSnippet(): JSX.Element {
    const [withRecordings, setWithRecordings] = useState(true)
    const { currentTeam } = useValues(teamLogic)

    const arrayJs = withRecordings ? 'array.full.js' : 'array.js'

    return (
        <>
            <CodeSnippet language={Language.HTML}>{`<script>
    !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host+"/static/${arrayJs}",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);
    posthog.init('${currentTeam?.api_token}',{api_host:'${window.location.origin}'})
</script>`}</CodeSnippet>
            <div className="flex gap-2 items-center">
                <LemonCheckbox
                    checked={withRecordings}
                    onChange={setWithRecordings}
                    bordered
                    label={<>Pre-load Session Recordings code </>}
                />
                <Tooltip
                    title={
                        <>
                            If you are using Session Recordings, this loads a slightly different snippet that includes
                            the extra code usually loaded at runtime.
                            <br />
                            <br />
                            This improves the startup time of recordings and reduces the chance that an adblocker gets
                            in the way.
                            <br />
                            <br />
                            If you are not intending to use Session Recordings, you can turn this off.
                        </>
                    }
                >
                    <IconInfo className="text-muted-alt text-lg" />
                </Tooltip>
            </div>
        </>
    )
}
