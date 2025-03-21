import { actions, kea, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'

import { PaymentsTab } from '~/types'

import type { paymentsSceneLogicType } from './paymentsSceneLogicType'

export const paymentsSceneLogic = kea<paymentsSceneLogicType>([
    path(['scenes', 'payments', 'paymentsSceneLogic']),
    actions({
        setTab: (tab: PaymentsTab) => ({ tab }),
    }),
    reducers(() => ({
        tab: [PaymentsTab.Overview as PaymentsTab, { setTab: (_, { tab }) => tab }],
    })),
    urlToAction(({ actions }) => ({
        [urls.paymentsOverview()]: () => actions.setTab(PaymentsTab.Overview),
        [urls.paymentsProducts()]: () => actions.setTab(PaymentsTab.Products),
        [urls.paymentsTransactions()]: () => actions.setTab(PaymentsTab.Transactions),
        [urls.paymentsSettings()]: () => actions.setTab(PaymentsTab.Settings),
    })),
])
