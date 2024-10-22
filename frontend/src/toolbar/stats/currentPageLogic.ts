import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers } from 'kea'

import type { currentPageLogicType } from './currentPageLogicType'

const replaceWithWildcard = (part: string): string => {
    // replace uuids
    if (part.match(/^([a-f]|[0-9]){8}-([a-f]|[0-9]){4}-([a-f]|[0-9]){4}-([a-f]|[0-9]){4}-([a-f]|[0-9]){12}$/)) {
        return '*'
    }

    // replace digits
    if (part.match(/^[0-9]+$/)) {
        return '*'
    }

    // Replace long values
    if (part.length > 24) {
        return '*'
    }

    return part
}

/**
 * Some implementations are able to set the href before the posthog init fragment is removed
 * we never want to store it as it will mean the heatmap URL is too specific and doesn't match
 * this ensures we never store it
 */
export function withoutPostHogInit(href: string): string {
    try {
        const url = new URL(href)
        url.hash = url.hash.replace(/__posthog=\{[^}]*}[^#]*/, '').replace(/^##/, '#')
        url.hash = url.hash === '#' ? '' : url.hash
        return url.toString()
    } catch {
        return href
    }
}

export const currentPageLogic = kea<currentPageLogicType>([
    path(['toolbar', 'stats', 'currentPageLogic']),
    actions(() => ({
        setHref: (href: string) => ({ href }),
        setWildcardHref: (href: string) => ({ href }),
        autoWildcardHref: true,
    })),
    reducers(() => ({
        href: [window.location.href, { setHref: (_, { href }) => withoutPostHogInit(href) }],
        wildcardHref: [
            window.location.href,
            {
                setHref: (_, { href }) => withoutPostHogInit(href),
                setWildcardHref: (_, { href }) => withoutPostHogInit(href),
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        autoWildcardHref: () => {
            let url = values.wildcardHref

            const urlParts = url.split('?')

            url = urlParts[0]
                .split('/')
                .map((part) => replaceWithWildcard(part))
                .join('/')

            // Iterate over query params and do the same for their values
            if (urlParts.length > 1) {
                const queryParams = urlParts[1].split('&')
                for (let i = 0; i < queryParams.length; i++) {
                    const [key, value] = queryParams[i].split('=')
                    queryParams[i] = `${key}=${replaceWithWildcard(value)}`
                }
                url = `${url}?${queryParams.join('&')}`
            }

            actions.setWildcardHref(url)
        },
    })),

    afterMount(({ actions, values, cache }) => {
        cache.interval = window.setInterval(() => {
            if (window.location.href !== values.href) {
                actions.setHref(window.location.href)
            }
        }, 500)
    }),

    beforeUnmount(({ cache }) => {
        window.clearInterval(cache.interval)
    }),
])
