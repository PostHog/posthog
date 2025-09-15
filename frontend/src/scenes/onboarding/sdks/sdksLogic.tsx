import { actions, afterMount, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import api from 'lib/api'
import { LemonSelectOptions } from 'lib/lemon-ui/LemonSelect/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { liveEventsTableLogic } from 'scenes/activity/live/liveEventsTableLogic'
import { userLogic } from 'scenes/userLogic'

import { hogql } from '~/queries/utils'
import { ProductKey, SDK, SDKInstructionsMap, SDKTag } from '~/types'

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

/*
Products that will often be installed in multiple places, eg. web and mobile
*/
export const multiInstallProducts = [ProductKey.PRODUCT_ANALYTICS, ProductKey.FEATURE_FLAGS]

export const sdksLogic = kea<sdksLogicType>([
    path(['scenes', 'onboarding', 'sdks', 'sdksLogic']),
    connect(() => ({
        values: [
            onboardingLogic,
            ['productKey'],
            liveEventsTableLogic({ tabId: 'onboarding' }),
            ['eventHosts'],
            featureFlagLogic,
            ['featureFlags'],
            userLogic,
            ['user', 'isUserNonTechnical'],
        ],
        actions: [eventUsageLogic, ['reportSDKSelected']],
    })),
    actions({
        setSourceFilter: (sourceFilter: string | null) => ({ sourceFilter }),
        filterSDKs: true,
        setSDKs: (sdks: SDK[]) => ({ sdks }),
        setSelectedSDK: (sdk: SDK | null) => ({ sdk }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSelectedTag: (selectedTag: SDKTag | null) => ({ selectedTag }),
        setSourceOptions: (sourceOptions: LemonSelectOptions<string>) => ({ sourceOptions }),
        resetSDKs: true,
        setAvailableSDKInstructionsMap: (sdkInstructionMap: SDKInstructionsMap) => ({ sdkInstructionMap }),
        setShowSideBySide: (showSideBySide: boolean) => ({ showSideBySide }),
        setPanel: (panel: 'instructions' | 'options') => ({ panel }),
        setHasSnippetEvents: (hasSnippetEvents: boolean) => ({ hasSnippetEvents }),
        setSnippetHosts: (snippetHosts: string[]) => ({ snippetHosts }),
        selectSDK: (sdk: SDK) => ({ sdk }),
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
        hasSnippetEvents: {
            setHasSnippetEvents: (_, { hasSnippetEvents }) => hasSnippetEvents,
        },
        snippetHosts: [
            [] as string[],
            {
                setSnippetHosts: (_, { snippetHosts }) => snippetHosts,
            },
        ],
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        selectedTag: [
            null as SDKTag | null,
            {
                setSelectedTag: (_, { selectedTag }) => selectedTag,
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
        combinedSnippetAndLiveEventsHosts: [
            (selectors) => [selectors.snippetHosts, selectors.eventHosts],
            // if the connected kea hasn't mounted for some reason, eventHosts can be undefined
            (snippetHosts: string[], eventHosts?: string[]): string[] => {
                const combinedSnippetAndLiveEventsHosts = snippetHosts
                for (const host of eventHosts ?? []) {
                    const hostProtocol = new URL(host).protocol
                    const currentProtocol = window.location.protocol
                    if (hostProtocol === currentProtocol && !combinedSnippetAndLiveEventsHosts.includes(host)) {
                        combinedSnippetAndLiveEventsHosts.push(host)
                    }
                }
                return combinedSnippetAndLiveEventsHosts
            },
        ],
        tags: [
            (s) => [s.sdks],
            (sdks: SDK[]): string[] => {
                const tagsWithSDKs = Object.values(SDKTag).filter((tag: SDKTag) =>
                    sdks.some((sdk) => sdk.tags.includes(tag))
                )
                return ['All', ...tagsWithSDKs]
            },
        ],
    }),
    loaders(({ actions }) => ({
        hasSnippetEvents: [
            null as boolean | null,
            {
                loadSnippetEvents: async () => {
                    const query = hogql`
                        SELECT
                            max(timestamp) AS latest_timestamp,
                            concat(
                                concat({protocol}, '//'),
                                properties.$host
                            ) AS full_host,
                        FROM events
                        WHERE timestamp >= now() - INTERVAL 3 DAY
                        AND timestamp <= now()
                        AND properties.$lib = 'web'
                        AND properties.$host is not null
                        AND startsWith(properties.$current_url, {protocol})
                        GROUP BY full_host
                        ORDER BY latest_timestamp DESC
                        LIMIT 7`

                    const res = await api.queryHogQL(query, {
                        queryParams: {
                            values: {
                                protocol: window.location.protocol,
                            },
                        },
                    })
                    const hasEvents = !!(res.results?.length ?? 0 > 0)
                    const snippetHosts = res.results?.map((result) => result[1]).filter((val) => !!val) ?? []
                    if (hasEvents) {
                        actions.setSnippetHosts(snippetHosts)
                    }
                    return hasEvents
                },
            },
        ],
    })),
    selectors({
        filteredSDKs: [
            (s) => [s.sdks, s.searchTerm, s.selectedTag],
            (sdks: SDK[], searchTerm: string, selectedTag: SDKTag | null): SDK[] => {
                return sdks.filter((sdk) => {
                    if (selectedTag && !sdk.tags.includes(selectedTag)) {
                        return false
                    }
                    if (searchTerm && !sdk.name.toLowerCase().includes(searchTerm.toLowerCase())) {
                        return false
                    }
                    return true
                })
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
                    return sdk.tags.includes(values.sourceFilter as SDKTag)
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
        selectSDK: ({ sdk }) => {
            actions.setSelectedSDK(sdk)
            actions.reportSDKSelected(sdk)
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.filterSDKs()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSnippetEvents()
    }),
    urlToAction(({ actions }) => ({
        '/onboarding/:productKey': (_productKey, { sdk }) => {
            const matchedSDK = allSDKs.find((s) => s.key === sdk)
            if (matchedSDK) {
                actions.setSelectedSDK(matchedSDK)
            }
        },
    })),
])
