import { Tooltip } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { IconCalculate, IconClipboardEdit } from 'lib/lemon-ui/icons'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import { BasicListItem, ExtendedListItem, ListItemAccordion, SidebarCategory } from '~/layout/navigation-3000/types'
import { DatabaseSchemaTableCommon } from '~/queries/schema'
import { DataWarehouseSavedQuery, PipelineTab } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../viewLinkLogic'
import { editorSceneLogic } from './editorSceneLogic'
import type { editorSidebarLogicType } from './editorSidebarLogicType'
import { multitabEditorLogic } from './multitabEditorLogic'

const sourcesTableFuse = new Fuse<DatabaseSchemaTableCommon>([], {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

const savedQueriesfuse = new Fuse<DataWarehouseSavedQuery>([], {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

export const editorSidebarLogic = kea<editorSidebarLogicType>([
    path(['data-warehouse', 'editor', 'editorSidebarLogic']),
    connect({
        values: [
            sceneLogic,
            ['activeScene', 'sceneParams'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById', 'initialDataWarehouseSavedQueryLoading'],
            databaseTableListLogic,
            ['posthogTables', 'dataWarehouseTables', 'databaseLoading', 'views', 'viewsMapById'],
        ],
        actions: [
            editorSceneLogic,
            ['selectSchema'],
            dataWarehouseViewsLogic,
            ['deleteDataWarehouseSavedQuery', 'runDataWarehouseSavedQuery'],
            viewLinkLogic,
            ['selectSourceTable', 'toggleJoinTableModal'],
        ],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [
                s.relevantSavedQueries,
                s.initialDataWarehouseSavedQueryLoading,
                s.relevantSources,
                s.dataWarehouseTablesBySourceType,
                s.databaseLoading,
            ],
            (
                relevantSavedQueries,
                initialDataWarehouseSavedQueryLoading,
                relevantSources,
                dataWarehouseTablesBySourceType,
                databaseLoading
            ) => [
                {
                    key: 'data-warehouse-views',
                    noun: ['view', 'views'],
                    loading: initialDataWarehouseSavedQueryLoading,
                    items: relevantSavedQueries.map(([savedQuery, matches]) => ({
                        key: savedQuery.id,
                        name: savedQuery.name,
                        url: '',
                        icon: savedQuery.status ? (
                            <Tooltip title="Materialized view">
                                <IconCalculate />
                            </Tooltip>
                        ) : (
                            <Tooltip title="View">
                                <IconClipboardEdit />
                            </Tooltip>
                        ),
                        searchMatch: matches
                            ? {
                                  matchingFields: matches.map((match) => match.key),
                                  nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                              }
                            : null,
                        onClick: () => {
                            actions.selectSchema(savedQuery)
                        },
                        menuItems: [
                            {
                                label: 'Edit view definition',
                                onClick: () => {
                                    multitabEditorLogic({
                                        key: `hogQLQueryEditor/${router.values.location.pathname}`,
                                    }).actions.editView(savedQuery.query.query, savedQuery)
                                },
                            },
                            {
                                label: 'Add join',
                                onClick: () => {
                                    actions.selectSourceTable(savedQuery.name)
                                    actions.toggleJoinTableModal()
                                },
                            },
                            {
                                label: 'Delete',
                                status: 'danger',
                                onClick: () => {
                                    actions.deleteDataWarehouseSavedQuery(savedQuery.id)
                                },
                            },
                        ],
                    })),
                } as SidebarCategory,
                {
                    key: 'sources',
                    noun: ['source', 'sources'],
                    loading: databaseLoading,
                    items:
                        relevantSources.length > 0
                            ? relevantSources.map(([table, matches]) => ({
                                  key: table.id,
                                  name: table.name,
                                  url: '',
                                  searchMatch: matches
                                      ? {
                                            matchingFields: matches.map((match) => match.key),
                                            nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                        }
                                      : null,
                                  onClick: () => {
                                      actions.selectSchema(table)
                                  },
                                  menuItems: [
                                      {
                                          label: 'Add join',
                                          onClick: () => {
                                              actions.selectSourceTable(table.name)
                                              actions.toggleJoinTableModal()
                                          },
                                      },
                                  ],
                              }))
                            : dataWarehouseTablesBySourceType,
                    onAdd: () => {
                        router.actions.push(urls.pipeline(PipelineTab.Sources))
                    },
                } as SidebarCategory,
            ],
        ],
        nonMaterializedViews: [
            (s) => [s.dataWarehouseSavedQueries],
            (views): DataWarehouseSavedQuery[] => {
                return views.filter((view) => !view.status)
            },
        ],
        materializedViews: [
            (s) => [s.dataWarehouseSavedQueries],
            (views): DataWarehouseSavedQuery[] => {
                return views.filter((view) => view.status)
            },
        ],
        activeListItemKey: [
            (s) => [s.activeScene, s.sceneParams],
            (activeScene, sceneParams): [string, number] | null => {
                return activeScene === Scene.DataWarehouse && sceneParams.params.id
                    ? ['saved-queries', parseInt(sceneParams.params.id)]
                    : null
            },
        ],
        dataWarehouseTablesBySourceType: [
            (s) => [s.dataWarehouseTables, s.posthogTables],
            (dataWarehouseTables, posthogTables): BasicListItem[] | ExtendedListItem[] | ListItemAccordion[] => {
                const tablesBySourceType = dataWarehouseTables.reduce(
                    (acc: Record<string, DatabaseSchemaTableCommon[]>, table) => {
                        if (table.source) {
                            if (!acc[table.source.source_type]) {
                                acc[table.source.source_type] = []
                            }
                            acc[table.source.source_type].push(table)
                        } else {
                            if (!acc['Self-managed']) {
                                acc['Self-managed'] = []
                            }
                            acc['Self-managed'].push(table)
                        }
                        return acc
                    },
                    {}
                )

                tablesBySourceType['Posthog'] = posthogTables

                return Object.entries(tablesBySourceType).map(([sourceType, tables]) => ({
                    key: sourceType,
                    noun: [sourceType, sourceType],
                    items: tables.map((table) => ({
                        key: table.id,
                        name: table.name,
                        url: '',
                        searchMatch: null,
                        onClick: () => {
                            actions.selectSchema(table)
                        },
                        menuItems: [
                            {
                                label: 'Add join',
                                onClick: () => {
                                    actions.selectSourceTable(table.name)
                                    actions.toggleJoinTableModal()
                                },
                            },
                        ],
                    })),
                })) as ListItemAccordion[]
            },
        ],
        relevantSavedQueries: [
            (s) => [s.dataWarehouseSavedQueries, navigation3000Logic.selectors.searchTerm],
            (dataWarehouseSavedQueries, searchTerm): [DataWarehouseSavedQuery, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return savedQueriesfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return dataWarehouseSavedQueries.map((savedQuery) => [savedQuery, null])
            },
        ],
        relevantSources: [
            () => [navigation3000Logic.selectors.searchTerm],
            (searchTerm): [DatabaseSchemaTableCommon, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return sourcesTableFuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return []
            },
        ],
    })),
    subscriptions(({ values }) => ({
        dataWarehouseTables: (dataWarehouseTables) => {
            sourcesTableFuse.setCollection([...dataWarehouseTables, ...values.posthogTables])
        },
        posthogTables: (posthogTables) => {
            sourcesTableFuse.setCollection([...values.dataWarehouseTables, ...posthogTables])
        },
        dataWarehouseSavedQueries: (dataWarehouseSavedQueries) => {
            savedQueriesfuse.setCollection(dataWarehouseSavedQueries)
        },
    })),
])
