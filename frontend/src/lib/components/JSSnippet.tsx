import { useValues } from 'kea'
import posthog from 'posthog-js'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { domainFor, proxyLogic } from 'scenes/settings/environment/proxyLogic'
import { teamLogic } from 'scenes/teamLogic'

function snippetFunctions(arrayJs = '/static/array.js'): string {
    const methods: string[] = []
    const posthogPrototype = Object.getPrototypeOf(posthog)
    for (const key of Object.getOwnPropertyNames(posthogPrototype)) {
        if (
            typeof posthogPrototype[key] === 'function' &&
            !key.startsWith('_') &&
            !['constructor', 'toString', 'push'].includes(key)
        ) {
            methods.push(key)
        }
    }
    const snippetMethods = methods.join(' ')

    return `!function(t,e){var o,n,p,r;e.__SV||(window.posthog && window.posthog.__loaded)||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"${arrayJs}",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="${snippetMethods}".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);`
}

type SnippetOption = {
    content: string
    enabled: boolean
    comment?: string
}

export function useJsSnippet(indent = 0, arrayJs?: string, scriptAttributes?: string): string {
    const { currentTeam } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { proxyRecords } = useValues(proxyLogic)
    const proxyRecord = proxyRecords[0]

    const isPersonProfilesDisabled = featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]

    const options: Record<string, SnippetOption> = {
        api_host: {
            content: domainFor(proxyRecord),
            comment: proxyRecord ? 'your managed reverse proxy domain' : undefined,
            enabled: true,
        },
        ui_host: {
            content: apiHostOrigin(),
            comment: "necessary because you're using a proxy, this way links will point back to PostHog properly",
            enabled: !!proxyRecord,
        },
        defaults: {
            content: '2025-05-24',
            enabled: true,
        },
        person_profiles: {
            content: 'identified_only',
            comment: "or 'always' to create profiles for anonymous users as well",
            enabled: !isPersonProfilesDisabled,
        },
    }

    const scriptTag = scriptAttributes ? `<script ${scriptAttributes}>` : '<script>'

    return [
        scriptTag,
        `    ${snippetFunctions(arrayJs)}`,
        `    posthog.init('${currentTeam?.api_token}', {`,
        ...Object.entries(options)
            .map(([key, value]) => {
                if (value.enabled) {
                    return `        ${key}: '${value.content}',${value.comment ? ` // ${value.comment}` : ''}`
                }
            })
            .filter(Boolean),
        `    })`,
        '</script>',
    ]
        .map((x) => ' '.repeat(indent) + x)
        .join('\n')
}

export function JSSnippet(): JSX.Element {
    const snippet = useJsSnippet()

    return <CodeSnippet language={Language.HTML}>{snippet}</CodeSnippet>
}

export function JSSnippetV2(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)

    const snippet = useJsSnippet(0, `/array/${currentTeam?.api_token}/array.js`)

    return <CodeSnippet language={Language.HTML}>{snippet}</CodeSnippet>
}
