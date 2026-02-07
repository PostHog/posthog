import Fuse from 'fuse.js'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'

import api from 'lib/api'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import type { taxonomicBreakdownComboboxLogicType } from './taxonomicBreakdownComboboxLogicType'

export interface BreakdownComboboxItem {
    id: string
    value: TaxonomicFilterValue
    name: string
    groupType: TaxonomicFilterGroupType
    taxonomicGroup: TaxonomicFilterGroup
    icon?: JSX.Element
}

export interface BreakdownComboboxGroup {
    type: TaxonomicFilterGroupType
    name: string
    items: BreakdownComboboxItem[]
}

export interface TaxonomicBreakdownComboboxLogicProps {
    insightProps: InsightLogicProps
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    eventNames: string[]
    schemaColumns: DatabaseSchemaField[]
    taxonomicFilterLogicKey: string
}

export interface RemoteGroupResults {
    [groupType: string]: any[]
}

export const taxonomicBreakdownComboboxLogic = kea<taxonomicBreakdownComboboxLogicType>([
    props({} as TaxonomicBreakdownComboboxLogicProps),
    key((props) => `${keyForInsightLogicProps('new')(props.insightProps)}`),
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownComboboxLogic']),
    connect((props: TaxonomicBreakdownComboboxLogicProps) => ({
        values: [
            taxonomicFilterLogic({
                taxonomicFilterLogicKey: props.taxonomicFilterLogicKey,
                taxonomicGroupTypes: props.taxonomicGroupTypes,
                eventNames: props.eventNames,
                schemaColumns: props.schemaColumns,
            }),
            ['taxonomicGroups'],
        ],
    })),
    actions({
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
    }),
    reducers({
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        remoteResults: [
            {} as RemoteGroupResults,
            {
                loadRemoteResults: async (_, breakpoint) => {
                    await breakpoint(300)

                    const { searchQuery } = values
                    const relevantGroups = values.taxonomicGroups.filter(
                        (g) =>
                            props.taxonomicGroupTypes.includes(g.type) &&
                            g.endpoint &&
                            g.type !== TaxonomicFilterGroupType.HogQLExpression
                    )

                    const results: RemoteGroupResults = {}

                    const promises = relevantGroups.map(async (group) => {
                        try {
                            const searchAlias = group.searchAlias || 'search'
                            const url = combineUrl(group.endpoint!, {
                                [searchAlias]: searchQuery,
                                limit: 20,
                                offset: 0,
                            }).url
                            const response = await api.get(url)
                            results[group.type] = response.results || response || []
                        } catch {
                            results[group.type] = []
                        }
                    })

                    await Promise.all(promises)
                    breakpoint()

                    return results
                },
            },
        ],
    })),
    selectors({
        relevantTaxonomicGroups: [
            (s, p) => [s.taxonomicGroups, p.taxonomicGroupTypes],
            (taxonomicGroups, taxonomicGroupTypes): TaxonomicFilterGroup[] =>
                taxonomicGroups.filter((g) => taxonomicGroupTypes.includes(g.type)),
        ],
        localItems: [
            (s) => [s.relevantTaxonomicGroups, s.searchQuery],
            (groups, searchQuery): RemoteGroupResults => {
                const results: RemoteGroupResults = {}
                for (const group of groups) {
                    if (!group.options || group.endpoint) {
                        continue
                    }
                    if (group.type === TaxonomicFilterGroupType.HogQLExpression) {
                        continue
                    }

                    let items = group.options as any[]

                    if (searchQuery) {
                        if (group.localItemsSearch) {
                            items = group.localItemsSearch(items, searchQuery)
                        } else {
                            const fuse = new Fuse(items, {
                                keys: ['name', 'id'],
                                threshold: 0.3,
                            })
                            items = fuse.search(searchQuery).map((r) => r.item)
                        }
                    }

                    results[group.type] = items
                }
                return results
            },
        ],
        allGroupedItems: [
            (s) => [s.relevantTaxonomicGroups, s.localItems, s.remoteResults],
            (groups, localItems, remoteResults): BreakdownComboboxGroup[] => {
                const result: BreakdownComboboxGroup[] = []

                for (const group of groups) {
                    if (group.type === TaxonomicFilterGroupType.HogQLExpression) {
                        continue
                    }

                    const rawItems = localItems[group.type] || remoteResults[group.type] || []
                    const getName = group.getName || ((item: any) => item.name || String(item))
                    const getValue = group.getValue || ((item: any) => item.name || item.value || item.id)
                    const getIcon = group.getIcon

                    const items: BreakdownComboboxItem[] = rawItems.map((item: any) => {
                        const name = getName(item)
                        const value = getValue(item)
                        return {
                            id: `${group.type}::${value}`,
                            value,
                            name: String(name),
                            groupType: group.type,
                            taxonomicGroup: group,
                            icon: getIcon ? getIcon(item) : undefined,
                        }
                    })

                    if (items.length > 0) {
                        result.push({
                            type: group.type,
                            name: group.name,
                            items,
                        })
                    }
                }

                return result
            },
        ],
        allItems: [(s) => [s.allGroupedItems], (groups): BreakdownComboboxItem[] => groups.flatMap((g) => g.items)],
        hasHogQLGroup: [
            (_s, p) => [p.taxonomicGroupTypes],
            (taxonomicGroupTypes): boolean => taxonomicGroupTypes.includes(TaxonomicFilterGroupType.HogQLExpression),
        ],
    }),
    listeners(({ actions }) => ({
        setSearchQuery: () => {
            actions.loadRemoteResults({})
        },
    })),
])
