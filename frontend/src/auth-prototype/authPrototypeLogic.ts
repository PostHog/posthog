import { kea, path } from 'kea'
import { router, urlToAction } from 'kea-router'

export const authPrototypeLogic = kea([
    path(['auth-prototype', 'authPrototypeLogic']),
    urlToAction({
        '*': (): void => {
            if (router.values.location.pathname.replace(/\/$/, '') !== '/login') {
                window.location.replace(window.location.href)
            }
        },
    }),
])
