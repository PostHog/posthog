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

import { DatabaseSchemaField } from '~/queries/schema/schema-general'

import type { dashboardPropertyFilterComboboxLogicType } from './dashboardPropertyFilterComboboxLogicType'

export interface PropertyComboboxItem {
    id: string
    value: TaxonomicFilterValue
    name: string
    groupType: TaxonomicFilterGroupType
    taxonomicGroup: TaxonomicFilterGroup
    isRemote: boolean
    icon?: JSX.Element
}

export interface PropertyComboboxGroup {
    type: TaxonomicFilterGroupType
    name: string
    items: PropertyComboboxItem[]
    isRemote: boolean
}

export interface DashboardPropertyFilterComboboxLogicProps {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    eventNames: string[]
    schemaColumns: DatabaseSchemaField[]
    taxonomicFilterLogicKey: string
}

export interface RemoteGroupResults {
    [groupType: string]: any[]
}

export const dashboardPropertyFilterComboboxLogic = kea<dashboardPropertyFilterComboboxLogicType>([
    props({} as DashboardPropertyFilterComboboxLogicProps),
    key((props) => props.taxonomicFilterLogicKey),
    path(['scenes', 'dashboard', 'dashboardPropertyFilterComboboxLogic']),
    connect((props: DashboardPropertyFilterComboboxLogicProps) => ({
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
        rawGroupedItems: [
            (s) => [s.relevantTaxonomicGroups, s.remoteResults],
            (groups, remoteResults): PropertyComboboxGroup[] => {
                const result: PropertyComboboxGroup[] = []

                for (const group of groups) {
                    if (group.type === TaxonomicFilterGroupType.HogQLExpression) {
                        continue
                    }

                    const isRemote = !!group.endpoint
                    const rawItems = isRemote ? remoteResults[group.type] || [] : (group.options as any[]) || []

                    const getName = group.getName || ((item: any) => item.name || String(item))
                    const getValue = group.getValue || ((item: any) => item.name || item.value || item.id)
                    const getIcon = group.getIcon

                    const items: PropertyComboboxItem[] = rawItems.map((item: any) => {
                        const name = getName(item)
                        const value = getValue(item)
                        return {
                            id: `${group.type}::${value}`,
                            value,
                            name: String(name),
                            groupType: group.type,
                            taxonomicGroup: group,
                            isRemote,
                            icon: getIcon ? getIcon(item) : undefined,
                        }
                    })

                    if (items.length > 0) {
                        result.push({
                            type: group.type,
                            name: group.name,
                            items,
                            isRemote,
                        })
                    }
                }

                return result
            },
        ],
        allRawItems: [(s) => [s.rawGroupedItems], (groups): PropertyComboboxItem[] => groups.flatMap((g) => g.items)],
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
