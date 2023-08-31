import { kea } from 'kea'

import type { sdksLogicType } from './sdksLogicType'
import { ProductKey, SDK } from '~/types'
import { onboardingLogic } from '../onboardingLogic'
import { ProductAnalyticsSDKInstructions } from './product-analytics/ProductAnalyticsSDKInstructions'
import { allSDKs } from './allSDKs'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect/LemonSelect'

export const productAvailableSDKs = {
    [ProductKey.PRODUCT_ANALYTICS]: ProductAnalyticsSDKInstructions,
}

const getSourceOptions = (productKey: string): LemonSelectOptions<string> => {
    const filteredSDKsTags = allSDKs
        .filter((sdk) => Object.keys(productAvailableSDKs[productKey || '']).includes(sdk.key))
        .flatMap((sdk) => sdk.tags)
    const uniqueTags = filteredSDKsTags.filter((item, index) => filteredSDKsTags.indexOf(item) === index)
    const selectOptions = uniqueTags.map((tag) => ({
        label: tag.charAt(0).toUpperCase() + tag.slice(1),
        value: tag,
    }))
    return selectOptions
}

export const sdksLogic = kea<sdksLogicType>({
    path: ['scenes', 'onboarding', 'sdks', 'sdksLogic'],
    connect: {
        values: [onboardingLogic, ['productKey']],
    },
    actions: {
        setSourceFilter: (sourceFilter: string | null) => ({ sourceFilter }),
        filterSDKs: true,
        setSDKs: (sdks: SDK[]) => ({ sdks }),
        setSelectedSDK: (sdk: SDK | null) => ({ sdk }),
        setSourceOptions: (sourceOptions: LemonSelectOptions<string>) => ({ sourceOptions }),
        resetSDKs: true,
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
        sourceOptions: [
            [] as LemonSelectOptions<string>,
            {
                setSourceOptions: (_, { sourceOptions }) => sourceOptions,
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        filterSDKs: () => {
            const filteredSDks: SDK[] = allSDKs
                .filter((sdk) => {
                    if (!values.sourceFilter || !sdk) {
                        return true
                    }
                    return sdk.tags.includes(values.sourceFilter)
                })
                .filter((sdk) => Object.keys(productAvailableSDKs[values.productKey || '']).includes(sdk.key))
            actions.setSDKs(filteredSDks)
            actions.setSourceOptions(getSourceOptions(values.productKey || ''))
        },
        setSourceFilter: () => {
            actions.filterSDKs()
            actions.setSelectedSDK(null)
        },
        [onboardingLogic.actionTypes.setProductKey]: () => {
            // TODO: This doesn't seem to run when the setProductKey action is called in onboardingLogic...
            actions.resetSDKs()
        },
        resetSDKs: () => {
            actions.filterSDKs()
            actions.setSelectedSDK(null)
            actions.setSourceFilter(null)
            actions.setSourceOptions(getSourceOptions(values.productKey || ''))
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.filterSDKs()
        },
    }),
})
