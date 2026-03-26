export type SnippetOption = {
    content: string
    enabled: boolean
    comment?: string
}

export function snippetFunctions(methods: string[], arrayJs = '/static/array.js'): string {
    const snippetMethods = methods.join(' ')

    return `!function(t,e){var o,n,p,r;e.__SV||(window.posthog && window.posthog.__loaded)||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]),t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host.replace(".i.posthog.com","-assets.i.posthog.com")+"${arrayJs}",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(void 0!==a?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+".people (stub)"},o="${snippetMethods}".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||[]);`
}

export interface BuildJsHtmlSnippetConfig {
    projectToken: string
    methods: string[]
    options: Record<string, SnippetOption>
    indent?: number
    arrayJs?: string
    scriptAttributes?: string
}

export function buildJsHtmlSnippet({
    projectToken,
    methods,
    options,
    indent = 0,
    arrayJs,
    scriptAttributes,
}: BuildJsHtmlSnippetConfig): string {
    const scriptTag = scriptAttributes ? `<script ${scriptAttributes}>` : '<script>'

    return [
        scriptTag,
        `    ${snippetFunctions(methods, arrayJs)}`,
        `    posthog.init('${projectToken}', {`,
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
