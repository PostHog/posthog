import { connect, kea, path, selectors } from 'kea'
import { authorizedUrlListLogic, AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import type { sitesLogicType } from './sitesLogicType'

export const sitesLogic = kea<sitesLogicType>([
    path(['scenes', 'sites', 'sitesLogic']),
    connect({
        values: [
            authorizedUrlListLogic({ actionId: null, type: AuthorizedUrlListType.TOOLBAR_URLS }),
            ['authorizedUrls'],
        ],
    }),
    selectors({
        sites: [
            (s) => [s.authorizedUrls],
            (authorizedUrls) => {
                return authorizedUrls.map((au) => {
                    const u = new URL(au)
                    return u.host
                })
            },
        ],
    }),
])
