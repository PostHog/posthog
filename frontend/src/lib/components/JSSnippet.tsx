import { useValues } from 'kea'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import posthog from 'posthog-js'
import { teamLogic } from 'scenes/teamLogic'

export function snippetFunctions(): string {
    const methods: string[] = []
    const posthogPrototype = Object.getPrototypeOf(posthog)
    for (const key of Object.getOwnPropertyNames(posthogPrototype)) {
        if (
            typeof posthogPrototype[key] === 'function' &&
            !key.startsWith('_') &&
            !['constructor', 'toString'].includes(key)
        ) {
            methods.push(key)
        }
    }
    const snippetMethods = methods.join(' ')

    return `!function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="${snippetMethods}".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);`
}

export function useJsSnippet(indent = 0): string {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    return [
        '<script>',
        `    ${snippetFunctions()}`,
        `    posthog.init('${currentTeam?.api_token}',{api_host:'${apiHostOrigin()}', ${
            isPersonProfilesDisabled
                ? ``
                : `person_profiles: 'identified_only' // or 'always' to create profiles for anonymous users as well`
        }
        })`,
        '</script>',
    ]
        .map((x) => ' '.repeat(indent) + x)
        .join('\n')
}

export function JSSnippet(): JSX.Element {
    const snippet = useJsSnippet()

    return <CodeSnippet language={Language.HTML}>{snippet}</CodeSnippet>
}
