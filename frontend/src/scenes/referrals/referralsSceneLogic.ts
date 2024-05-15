import { actions, kea, path } from 'kea'
import { loaders } from 'kea-loaders'

import type { referralsSceneLogicType } from './referralsSceneLogicType'

export const referralsSceneLogic = kea<referralsSceneLogicType>([
    path(['scenes', 'referrals', 'referralsSceneLogic']),
    actions({}),

    loaders(() => ({
        referrals: {
            __default: [],
            loadReferrals: async () => {
                return []
            },
        },
    })),
])
