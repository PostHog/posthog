import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { ProductKey, ReferralProgram } from '~/types'

import type { referralsSceneLogicType } from './referralsSceneLogicType'

export const referralsSceneLogic = kea<referralsSceneLogicType>([
    path(['scenes', 'referrals', 'referralsSceneLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    actions({}),
    loaders(() => ({
        referrals: {
            __default: [] as ReferralProgram[],
            loadReferrals: async () => {
                const response = await api.referralPrograms.list()
                return response.results
            },
        },
    })),
    selectors(() => ({
        showIntro: [
            (s) => [s.referrals, s.referralsLoading, s.user],
            (referrals, referralsLoading, user) => {
                const shouldShowEmptyState = referrals.length == 0 && !referralsLoading
                const shouldShowProductIntroduction = !user?.has_seen_product_intro_for?.[ProductKey.REFERRALS]
                return shouldShowProductIntroduction || shouldShowEmptyState
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadReferrals()
    }),
])
