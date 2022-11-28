import { actions, kea, path, reducers, selectors } from 'kea'

import type { toolbarRedirectLogicType } from './toolbarRedirectLogicType'
import { urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

export const toolbarRedirectLogic = kea<toolbarRedirectLogicType>([
    path(['scenes', 'toolbar-redirect', 'toolbarRedirectLogic']),
    actions({
        setRedirect: (redirect: string | null) => ({ redirect }),
    }),
    reducers({
        redirect: [
            null as string | null,
            {
                setRedirect: (_, { redirect }) => redirect,
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        [urls.toolbarRedirect()]: (_, { redirect }) => actions.setRedirect(redirect),
        [urls.toolbarLaunch()]: () => actions.setRedirect(null),
    })),
    selectors({
        domain: [
            (s) => [s.redirect],
            (redirect) => {
                try {
                    return new URL(redirect || '').hostname
                } catch (e) {
                    return ''
                }
            },
        ],
    }),
])
