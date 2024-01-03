import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect/LemonSelect'

import { SDK, SDKInstructionsMap } from '~/types'

import { onboardingLogic } from '../onboardingLogic'
import { allSDKs } from './allSDKs'
import type { sdksLogicType } from './sdksLogicType'

/* 
To add SDK instructions for your product:
    1. If needed, add a new ProductKey enum value in ~/types.ts
    2. Create a folder in this directory for your product
    3. Create and export the instruction components
    4. Create a file like ProductAnalyticsSDKInstructions.tsx and export the instructions object with the SDKKey:Component mapping
    6. Add the SDK component to your product onboarding component
*/

const getSourceOptions = (availableSDKInstructionsMap: SDKInstructionsMap): LemonSelectOptions<string> => {
    const filteredSDKsTags = allSDKs
        .filter((sdk) => Object.keys(availableSDKInstructionsMap).includes(sdk.key))
        .flatMap((sdk) => sdk.tags)
    const uniqueTags = filteredSDKsTags.filter((item, index) => filteredSDKsTags.indexOf(item) === index)
    const selectOptions = uniqueTags.map((tag) => ({
        label: tag,
        value: tag,
    }))
    return selectOptions
}

export const sdksLogic = kea<sdksLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'sdksLogic']),
    connect({
        values: [onboardingLogic, ['productKey']],
    }),
    actions({
        setSourceFilter: (sourceFilter: string | null) => ({ sourceFilter }),
        filterSDKs: true,
        setSDKs: (sdks: SDK[]) => ({ sdks }),
        setSelectedSDK: (sdk: SDK | null) => ({ sdk }),
        setSourceOptions: (sourceOptions: LemonSelectOptions<string>) => ({ sourceOptions }),
        resetSDKs: true,
        setAvailableSDKInstructionsMap: (sdkInstructionMap: SDKInstructionsMap) => ({ sdkInstructionMap }),
        setShowSideBySide: (showSideBySide: boolean) => ({ showSideBySide }),
        setPanel: (panel: 'instructions' | 'options') => ({ panel }),
    }),
    reducers({
        sourceFilter: [
            null as string | null,
            {
                setSourceFilter: (_, { sourceFilter }) => sourceFilter,
            },
        ],
        sdks: [
            [] as SDK[] | null,
            {
                setSDKs: (_, { sdks }) => sdks,
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
        availableSDKInstructionsMap: [
            {} as SDKInstructionsMap,
            {
                setAvailableSDKInstructionsMap: (_, { sdkInstructionMap }) => sdkInstructionMap,
            },
        ],
        showSideBySide: [
            null as boolean | null,
            {
                setShowSideBySide: (_, { showSideBySide }) => showSideBySide,
            },
        ],
        panel: [
            'options' as 'instructions' | 'options',
            {
                setPanel: (_, { panel }) => panel,
            },
        ],
    }),
    selectors({
        showSourceOptionsSelect: [
            (selectors) => [selectors.sourceOptions, selectors.availableSDKInstructionsMap],
            (sourceOptions: LemonSelectOptions<string>, availableSDKInstructionsMap: SDKInstructionsMap): boolean => {
                // more than two source options since one will almost always be "recommended"
                // more than 5 sdks since with fewer you don't really need to filter
                return Object.keys(availableSDKInstructionsMap).length > 5 && sourceOptions.length > 2
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        filterSDKs: () => {
            const filteredSDks: SDK[] = allSDKs
                .filter((sdk) => {
                    if (!values.sourceFilter || !sdk) {
                        return true
                    }
                    return sdk.tags.includes(values.sourceFilter)
                })
                .filter((sdk) => Object.keys(values.availableSDKInstructionsMap).includes(sdk.key))
            actions.setSDKs(filteredSDks)
            actions.setSourceOptions(getSourceOptions(values.availableSDKInstructionsMap))
        },
        setAvailableSDKInstructionsMap: () => {
            actions.filterSDKs()
        },
        setSDKs: () => {
            if (!values.selectedSDK && values.showSideBySide == true) {
                actions.setSelectedSDK(values.sdks?.[0] || null)
            }
        },
        setSourceFilter: () => {
            actions.setSelectedSDK(null)
            actions.filterSDKs()
        },
        [onboardingLogic.actionTypes.setProductKey]: () => {
            // TODO: This doesn't seem to run when the setProductKey action is called in onboardingLogic...
            actions.resetSDKs()
        },
        resetSDKs: () => {
            actions.filterSDKs()
            actions.setSelectedSDK(null)
            actions.setSourceFilter(null)
            actions.setSourceOptions(getSourceOptions(values.availableSDKInstructionsMap))
        },
        setSelectedSDK: () => {
            if (values.selectedSDK) {
                actions.setPanel('instructions')
            }
        },
        setShowSideBySide: () => {
            if (values.showSideBySide && !values.selectedSDK) {
                actions.setSelectedSDK(values.sdks?.[0] || null)
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.filterSDKs()
        },
    })),
])
