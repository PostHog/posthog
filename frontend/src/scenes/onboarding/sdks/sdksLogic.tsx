import { kea } from 'kea'

import type { sdksLogicType } from './sdksLogicType'
import { ProductKey, SDK } from '~/types'
import { onboardingLogic } from '../onboardingLogic'
import { ProductAnalyticsSDKInstructions } from './ProductAnalyticsSDKInstructions'
import { allSDKs } from './allSDKs'

export const productAvailableSDKs = {
    [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsSDKInstructions,
}

export const sdksLogic = kea<sdksLogicType>({
    path: ['scenes', 'onboarding', 'sdks', 'sdksLogic'],
    connect: {
        values: [onboardingLogic, ['productKey']],
        actions: [onboardingLogic, ['setProductKey']],
    },
    actions: {
        setSourceFilter: (sourceFilter: string | null) => ({ sourceFilter }),
        filterSDKs: true,
        setSDKs: (sdks: SDK[]) => ({ sdks }),
        setSelectedSDK: (sdk: SDK) => ({ sdk }),
    },

    reducers: {
        sourceFilter: [
            null as string | null,
            {
                setSourceFilter: (_, { sourceFilter }) => sourceFilter,
            },
        ],
        sdks: [
            null as SDK[] | null,
            {
                setSDKs: (_, { sdks }) => sdks,
                setSourceFilter: (_, { sourceFilter }) => {
                    if (!sourceFilter) {
                        return allSDKs
                    }
                    return allSDKs.filter((sdk) => sdk.tags.includes(sourceFilter))
                },
            },
        ],
        selectedSDK: [
            null as SDK | null,
            {
                setSelectedSDK: (_, { sdk }) => sdk,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        filterSDKs: () => {
            const filteredSDks: SDK[] = allSDKs
                .filter((sdk) => Object.keys(productAvailableSDKs[values.productKey || '']).includes(sdk.key))
                .filter((sdk) => {
                    if (!values.sourceFilter) {
                        return true
                    }
                    return sdk.tags.includes(values.sourceFilter)
                })
            actions.setSDKs(filteredSDks)
        },
        setSourceFilter: () => {
            actions.filterSDKs()
        },
        setProductKey: () => {
            actions.filterSDKs()
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.filterSDKs()
        },
    }),
})
