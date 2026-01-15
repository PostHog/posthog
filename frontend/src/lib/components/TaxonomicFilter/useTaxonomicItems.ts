import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import React from 'react'

import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'

import { infiniteListLogic } from './infiniteListLogic'
import { taxonomicFilterLogic } from './taxonomicFilterLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from './types'

/**
 * Item format compatible with Base UI Autocomplete
 */
export interface TaxonomicSuggestionItem {
    id: string
    label: string
    value: string | number | null
    description: string
    icon?: JSX.Element
    groupType: TaxonomicFilterGroupType
    item: TaxonomicDefinitionTypes
}

/**
 * Group structure for grouped autocomplete
 */
export interface TaxonomicItemGroup {
    value: TaxonomicFilterGroupType
    name: string
    items: TaxonomicSuggestionItem[]
}

export interface UseTaxonomicItemsOptions {
    /** Key for the taxonomic filter logic instance */
    taxonomicFilterLogicKey: string
    /** Primary group types to show first (e.g., MaxAIContext for "On this page" items) */
    mainGroupTypes: TaxonomicFilterGroupType[]
    /** All available group types */
    allGroupTypes: TaxonomicFilterGroupType[]
    /** Search query to filter items */
    searchQuery?: string
    /** Maximum items per group (default: 50) */
    maxItemsPerGroup?: number
    /** Options for MaxAIContext group (e.g., "On this page" items) */
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
}

export interface UseTaxonomicItemsResult {
    /** Flat list of all items (main groups first, then others) */
    items: TaxonomicSuggestionItem[]
    /** Items organized by group - for use with Autocomplete.Group */
    groups: TaxonomicItemGroup[]
    /** Whether any group is currently loading */
    isLoading: boolean
}

/**
 * Helper hook to mount and get items from an infiniteListLogic instance
 */
function useInfiniteListItems(
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps,
    groupType: TaxonomicFilterGroupType,
    enabled: boolean
): { results: TaxonomicDefinitionTypes[]; isLoading: boolean } {
    const logic = infiniteListLogic({
        ...taxonomicFilterLogicProps,
        listGroupType: groupType,
    })

    const { results, isLoading } = useValues(logic)
    const { loadRemoteItems } = useActions(logic)

    useEffect(() => {
        if (enabled && results.length === 0) {
            loadRemoteItems({ offset: 0, limit: 100 })
        }
    }, [enabled, loadRemoteItems, results.length])

    return { results: enabled ? results : [], isLoading: enabled && isLoading }
}

/**
 * Hook to get taxonomic items for use in Base UI Autocomplete.
 * Mounts infiniteListLogic for each group type to fetch remote data.
 */
export function useTaxonomicItems({
    taxonomicFilterLogicKey,
    mainGroupTypes,
    allGroupTypes,
    searchQuery = '',
    maxItemsPerGroup = 50,
    maxContextOptions = [],
}: UseTaxonomicItemsOptions): UseTaxonomicItemsResult {
    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = useMemo(
        () => ({
            taxonomicFilterLogicKey,
            taxonomicGroupTypes: allGroupTypes,
            maxContextOptions,
        }),
        [taxonomicFilterLogicKey, allGroupTypes, maxContextOptions]
    )

    const { taxonomicGroups } = useValues(taxonomicFilterLogic(taxonomicFilterLogicProps))

    // Mount infiniteListLogic for each supported group type
    // These hooks must be called unconditionally
    const hasEvents = allGroupTypes.includes(TaxonomicFilterGroupType.Events)
    const hasActions = allGroupTypes.includes(TaxonomicFilterGroupType.Actions)
    const hasInsights = allGroupTypes.includes(TaxonomicFilterGroupType.Insights)
    const hasDashboards = allGroupTypes.includes(TaxonomicFilterGroupType.Dashboards)
    const hasErrorTracking = allGroupTypes.includes(TaxonomicFilterGroupType.ErrorTrackingIssues)

    const eventsData = useInfiniteListItems(taxonomicFilterLogicProps, TaxonomicFilterGroupType.Events, hasEvents)
    const actionsData = useInfiniteListItems(taxonomicFilterLogicProps, TaxonomicFilterGroupType.Actions, hasActions)
    const insightsData = useInfiniteListItems(taxonomicFilterLogicProps, TaxonomicFilterGroupType.Insights, hasInsights)
    const dashboardsData = useInfiniteListItems(
        taxonomicFilterLogicProps,
        TaxonomicFilterGroupType.Dashboards,
        hasDashboards
    )
    const errorTrackingData = useInfiniteListItems(
        taxonomicFilterLogicProps,
        TaxonomicFilterGroupType.ErrorTrackingIssues,
        hasErrorTracking
    )

    // Map group types to their loaded data
    const remoteDataMap = useMemo(
        () => ({
            [TaxonomicFilterGroupType.Events]: eventsData,
            [TaxonomicFilterGroupType.Actions]: actionsData,
            [TaxonomicFilterGroupType.Insights]: insightsData,
            [TaxonomicFilterGroupType.Dashboards]: dashboardsData,
            [TaxonomicFilterGroupType.ErrorTrackingIssues]: errorTrackingData,
        }),
        [eventsData, actionsData, insightsData, dashboardsData, errorTrackingData]
    )

    // Order: main groups first, then remaining groups
    const orderedGroupTypes = useMemo(() => {
        const mainSet = new Set(mainGroupTypes)
        const others = allGroupTypes.filter((t) => !mainSet.has(t))
        return [...mainGroupTypes, ...others]
    }, [mainGroupTypes, allGroupTypes])

    const result = useMemo(() => {
        const allItems: TaxonomicSuggestionItem[] = []
        const groups: TaxonomicItemGroup[] = []
        let isLoading = false
        const query = searchQuery.toLowerCase()

        for (const groupType of orderedGroupTypes) {
            const group = taxonomicGroups.find((g: TaxonomicFilterGroup) => g.type === groupType)
            if (!group) {
                continue
            }

            const groupItems: TaxonomicSuggestionItem[] = []

            // Get items from remote data or static options
            const remoteData = remoteDataMap[groupType as keyof typeof remoteDataMap]
            const rawItems: TaxonomicDefinitionTypes[] = remoteData?.results || []
            const staticOptions: any[] = group.options || []
            const itemsSource = rawItems.length > 0 ? rawItems : staticOptions

            if (remoteData?.isLoading) {
                isLoading = true
            }

            for (let i = 0; i < Math.min(itemsSource.length, maxItemsPerGroup); i++) {
                const item = itemsSource[i]
                if (!item) {
                    continue
                }

                const itemValue = group.getValue?.(item) ?? (item as any).value ?? null
                const itemName = group.getName?.(item) || (item as any).name || ''
                const icon = group.getIcon?.(item)

                // Filter by search query
                if (query && !itemName.toLowerCase().includes(query)) {
                    continue
                }

                groupItems.push({
                    id: `${groupType}-${i}-${itemValue}`,
                    label: itemName,
                    value: itemValue,
                    description: group.name,
                    icon: icon ? React.cloneElement(icon, { className: 'w-4 h-4' }) : undefined,
                    groupType,
                    item,
                })
            }

            if (groupItems.length > 0) {
                allItems.push(...groupItems)
                groups.push({
                    value: groupType,
                    name: group.name,
                    items: groupItems,
                })
            }
        }

        return { items: allItems, groups, isLoading }
    }, [orderedGroupTypes, taxonomicGroups, remoteDataMap, searchQuery, maxItemsPerGroup])

    return result
}
