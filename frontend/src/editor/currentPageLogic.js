import { kea } from 'kea'

export const currentPageLogic = kea({
    actions: () => ({
        setHref: href => ({ href }),
    }),
    reducers: () => ({
        href: [window.location.href, { setHref: (_, { href }) => href }],
    }),
})
