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

export const currentPageLogic = kea<currentPageLogicType>([
    path(['toolbar', 'stats', 'currentPageLogic']),
    actions(() => ({
        setHref: (href: string) => ({ href }),
        setWildcardHref: (href: string) => ({ href }),
        autoWildcardHref: true,
    })),
    reducers(() => ({
        href: [window.location.href, { setHref: (_, { href }) => href }],
        wildcardHref: [
            window.location.href,
            { setHref: (_, { href }) => href, setWildcardHref: (_, { href }) => href },
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
