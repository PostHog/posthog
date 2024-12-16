import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCalculate, IconClipboardEdit } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import { SidebarCategory } from '~/layout/navigation-3000/types'
import { DatabaseSchemaDataWarehouseTable, DatabaseSchemaTable } from '~/queries/schema'
import { DataWarehouseSavedQuery, PipelineTab } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { viewLinkLogic } from '../viewLinkLogic'
import { editorSceneLogic } from './editorSceneLogic'
import type { editorSidebarLogicType } from './editorSidebarLogicType'
import { multitabEditorLogic } from './multitabEditorLogic'

const dataWarehouseTablesfuse = new Fuse<DatabaseSchemaDataWarehouseTable>([], {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

const posthogTablesfuse = new Fuse<DatabaseSchemaTable>([], {
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

const nonMaterializedViewsfuse = new Fuse<DataWarehouseSavedQuery>([], {
    keys: [{ name: 'name', weight: 2 }],
    threshold: 0.3,
    ignoreLocation: true,
    includeMatches: true,
})

const materializedViewsfuse = new Fuse<DataWarehouseSavedQuery>([], {
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
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById', 'dataWarehouseSavedQueriesLoading'],
            databaseTableListLogic,
            ['posthogTables', 'dataWarehouseTables', 'databaseLoading', 'views', 'viewsMapById'],
            featureFlagLogic,
            ['featureFlags'],
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
                s.dataWarehouseSavedQueriesLoading,
                s.relevantPosthogTables,
                s.relevantDataWarehouseTables,
                s.databaseLoading,
                s.relevantNonMaterializedViews,
                s.relevantMaterializedViews,
                s.featureFlags,
            ],
            (
                relevantSavedQueries,
                dataWarehouseSavedQueriesLoading,
                relevantPosthogTables,
                relevantDataWarehouseTables,
                databaseLoading,
                relevantNonMaterializedViews,
                relevantMaterializedViews,
                featureFlags
            ) => [
                {
                    key: 'data-warehouse-sources',
                    noun: ['source', 'external source'],
                    loading: databaseLoading,
                    items: relevantDataWarehouseTables.map(([table, matches]) => ({
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
                    })),
                    onAdd: () => {
                        router.actions.push(urls.pipeline(PipelineTab.Sources))
                    },
                } as SidebarCategory,
                {
                    key: 'data-warehouse-tables',
                    noun: ['table', 'tables'],
                    loading: databaseLoading,
                    items: relevantPosthogTables.map(([table, matches]) => ({
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
                    })),
                } as SidebarCategory,
                {
                    key: 'data-warehouse-views',
                    noun: ['view', 'views'],
                    loading: dataWarehouseSavedQueriesLoading,
                    items: (featureFlags[FEATURE_FLAGS.DATA_MODELING]
                        ? relevantNonMaterializedViews
                        : relevantSavedQueries
                    ).map(([savedQuery, matches]) => ({
                        key: savedQuery.id,
                        name: savedQuery.name,
                        url: '',
                        icon: savedQuery.status ? <IconCalculate /> : <IconClipboardEdit />,
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
                            ...(featureFlags[FEATURE_FLAGS.DATA_MODELING] && !savedQuery.status
                                ? [
                                      {
                                          label: 'Materialize',
                                          onClick: () => {
                                              actions.runDataWarehouseSavedQuery(savedQuery.id)
                                          },
                                      },
                                  ]
                                : []),
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
                ...(featureFlags[FEATURE_FLAGS.DATA_MODELING]
                    ? [
                          {
                              key: 'data-warehouse-materialized-views',
                              noun: ['materialized view', 'materialized views'],
                              loading: dataWarehouseSavedQueriesLoading,
                              items: relevantMaterializedViews.map(([materializedView, matches]) => ({
                                  key: materializedView.id,
                                  name: materializedView.name,
                                  icon: <IconCalculate />,
                                  url: '',
                                  searchMatch: matches
                                      ? {
                                            matchingFields: matches.map((match) => match.key),
                                            nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                        }
                                      : null,
                                  onClick: () => {
                                      actions.selectSchema(materializedView)
                                  },
                                  menuItems: [
                                      {
                                          label: 'Edit view definition',
                                          onClick: () => {
                                              multitabEditorLogic({
                                                  key: `hogQLQueryEditor/${router.values.location.pathname}`,
                                              }).actions.createTab(materializedView.query.query, materializedView)
                                          },
                                      },
                                      {
                                          label: 'Add join',
                                          onClick: () => {
                                              actions.selectSourceTable(materializedView.name)
                                              actions.toggleJoinTableModal()
                                          },
                                      },
                                      ...(featureFlags[FEATURE_FLAGS.DATA_MODELING] && materializedView.status
                                          ? [
                                                {
                                                    label: 'Run',
                                                    onClick: () => {
                                                        actions.runDataWarehouseSavedQuery(materializedView.id)
                                                    },
                                                },
                                            ]
                                          : []),
                                      {
                                          label: 'Delete',
                                          status: 'danger',
                                          onClick: () => {
                                              actions.deleteDataWarehouseSavedQuery(materializedView.id)
                                          },
                                      },
                                  ],
                              })),
                          } as SidebarCategory,
                      ]
                    : []),
            ],
        ],
        nonMaterializedViews: [
            (s) => [s.dataWarehouseSavedQueries],
            (views): DataWarehouseSavedQuery[] => {
                return views.filter((view) => !view.status && !view.last_run_at)
            },
        ],
        materializedViews: [
            (s) => [s.dataWarehouseSavedQueries],
            (views): DataWarehouseSavedQuery[] => {
                return views.filter((view) => view.status || view.last_run_at)
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
        relevantDataWarehouseTables: [
            (s) => [s.dataWarehouseTables, navigation3000Logic.selectors.searchTerm],
            (dataWarehouseTables, searchTerm): [DatabaseSchemaDataWarehouseTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return dataWarehouseTablesfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return dataWarehouseTables.map((table) => [table, null])
            },
        ],
        relevantPosthogTables: [
            (s) => [s.posthogTables, navigation3000Logic.selectors.searchTerm],
            (posthogTables, searchTerm): [DatabaseSchemaTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return posthogTablesfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return posthogTables.map((table) => [table, null])
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
        relevantNonMaterializedViews: [
            (s) => [s.nonMaterializedViews, navigation3000Logic.selectors.searchTerm],
            (nonMaterializedViews, searchTerm): [DataWarehouseSavedQuery, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return nonMaterializedViewsfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return nonMaterializedViews.map((view) => [view, null])
            },
        ],
        relevantMaterializedViews: [
            (s) => [s.materializedViews, navigation3000Logic.selectors.searchTerm],
            (materializedViews, searchTerm): [DataWarehouseSavedQuery, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return materializedViewsfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return materializedViews.map((view) => [view, null])
            },
        ],
    })),
    subscriptions({
        dataWarehouseTables: (dataWarehouseTables) => {
            dataWarehouseTablesfuse.setCollection(dataWarehouseTables)
        },
        posthogTables: (posthogTables) => {
            posthogTablesfuse.setCollection(posthogTables)
        },
        dataWarehouseSavedQueries: (dataWarehouseSavedQueries) => {
            savedQueriesfuse.setCollection(dataWarehouseSavedQueries)
        },
    }),
])
