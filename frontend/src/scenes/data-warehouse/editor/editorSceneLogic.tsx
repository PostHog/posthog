import { IconDatabase, IconDocument } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { ProductIntentContext } from 'lib/utils/product-intents'
import posthog from 'posthog-js'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import { BasicListItem, ExtendedListItem, ListItemAccordion, SidebarCategory } from '~/layout/navigation-3000/types'
import { DatabaseSchemaDataWarehouseTable, DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery, PipelineStage, ProductKey } from '~/types'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { DataWarehouseSourceIcon, mapUrlToProvider } from '../settings/DataWarehouseSourceIcon'
import { viewLinkLogic } from '../viewLinkLogic'
import type { editorSceneLogicType } from './editorSceneLogicType'
import { multitabEditorLogic } from './multitabEditorLogic'
import { queryDatabaseLogic } from './sidebar/queryDatabaseLogic'

const dataWarehouseTablesfuse = new Fuse<DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable>([], {
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

export const editorSceneLogic = kea<editorSceneLogicType>([
    path(['data-warehouse', 'editor', 'editorSceneLogic']),
    connect(() => ({
        values: [
            sceneLogic,
            ['activeScene', 'sceneParams'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueries', 'dataWarehouseSavedQueryMapById', 'initialDataWarehouseSavedQueryLoading'],
            databaseTableListLogic,
            ['posthogTables', 'dataWarehouseTables', 'allTables', 'databaseLoading', 'views', 'viewsMapById'],
        ],
        actions: [
            queryDatabaseLogic,
            ['selectSchema'],
            dataWarehouseViewsLogic,
            ['deleteDataWarehouseSavedQuery', 'runDataWarehouseSavedQuery'],
            viewLinkLogic,
            ['selectSourceTable', 'toggleJoinTableModal'],
            teamLogic,
            ['addProductIntent'],
        ],
    })),
    actions({
        setSidebarOverlayOpen: (isOpen: boolean) => ({ isOpen }),
        reportAIQueryPrompted: true,
        reportAIQueryAccepted: true,
        reportAIQueryRejected: true,
        reportAIQueryPromptOpen: true,
    }),
    reducers({
        sidebarOverlayOpen: [
            false,
            {
                setSidebarOverlayOpen: (_, { isOpen }) => isOpen,
                selectSchema: (_, { schema }) => schema !== null,
            },
        ],
    }),
    listeners(() => ({
        reportAIQueryPrompted: () => {
            posthog.capture('ai_query_prompted')
        },
        reportAIQueryAccepted: () => {
            posthog.capture('ai_query_accepted')
        },
        reportAIQueryRejected: () => {
            posthog.capture('ai_query_rejected')
        },
        reportAIQueryPromptOpen: () => {
            posthog.capture('ai_query_prompt_open')
        },
    })),
    selectors(({ actions }) => ({
        contents: [
            (s) => [
                s.relevantSavedQueries,
                s.initialDataWarehouseSavedQueryLoading,
                s.relevantDataWarehouseTables,
                s.dataWarehouseTablesBySourceType,
                s.databaseLoading,
                navigation3000Logic.selectors.searchTerm,
            ],
            (
                relevantSavedQueries,
                initialDataWarehouseSavedQueryLoading,
                relevantDataWarehouseTables,
                dataWarehouseTablesBySourceType,
                databaseLoading,
                searchTerm
            ) => [
                {
                    key: 'data-warehouse-sources',
                    noun: ['source', 'sources'],
                    loading: databaseLoading,
                    items:
                        relevantDataWarehouseTables.length > 0
                            ? relevantDataWarehouseTables.map(([table, matches]) => ({
                                  key: table.id,
                                  icon: <IconDatabase />,
                                  name: table.name,
                                  url: '',
                                  searchMatch: matches
                                      ? {
                                            matchingFields: matches.map((match) => match.key),
                                            nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                                        }
                                      : null,
                                  onClick: () => {
                                      multitabEditorLogic({
                                          key: `hogQLQueryEditor/${router.values.location.pathname}`,
                                      }).actions.createTab(`SELECT * FROM ${table.name}`)
                                  },
                                  menuItems: [
                                      {
                                          label: 'Open schema',
                                          onClick: () => {
                                              actions.selectSchema(table)
                                          },
                                      },
                                      {
                                          label: 'Add join',
                                          onClick: () => {
                                              actions.selectSourceTable(table.name)
                                              actions.toggleJoinTableModal()
                                          },
                                      },
                                      {
                                          label: 'Copy table name',
                                          onClick: () => {
                                              void copyToClipboard(table.name)
                                          },
                                      },
                                  ],
                              }))
                            : dataWarehouseTablesBySourceType,
                    onAdd: () => {
                        router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                    },
                    emptyComponentLogic: (items) => {
                        // We will always show the posthog tables, so we wanna check for length == 1 instead of 0
                        return items.length < 2 && !databaseLoading && !searchTerm?.length
                    },
                    emptyComponent: (
                        <div className="p-4 text-center flex flex-col justify-center items-center border-t">
                            <div className="mb-4 flex justify-center gap-6">
                                <DataWarehouseSourceIcon type="Postgres" size="small" />
                                <DataWarehouseSourceIcon type="Stripe" size="small" />
                            </div>
                            <h4 className="mb-2">No data warehouse sources connected</h4>
                            {/* eslint-disable-next-line react/forbid-dom-props */}
                            <p className="text-muted mb-4 text-xs px-2 break-words w" style={{ whiteSpace: 'normal' }}>
                                Import data from external sources like Postgres, Stripe, or other databases to enrich
                                your analytics.
                            </p>
                            <LemonButton
                                type="primary"
                                onClick={() => {
                                    actions.addProductIntent({
                                        product_type: ProductKey.DATA_WAREHOUSE,
                                        intent_context: ProductIntentContext.SQL_EDITOR_EMPTY_STATE,
                                    })
                                    router.actions.push(urls.pipelineNodeNew(PipelineStage.Source))
                                }}
                                center
                                size="small"
                                id="data-warehouse-sql-editor-add-data-source"
                            >
                                Add data source
                            </LemonButton>
                        </div>
                    ),
                } as SidebarCategory,
                {
                    key: 'data-warehouse-views',
                    noun: ['view', 'views'],
                    loading: initialDataWarehouseSavedQueryLoading,
                    items: relevantSavedQueries.map(([savedQuery, matches]) => ({
                        key: savedQuery.id,
                        name: savedQuery.name,
                        url: '',
                        icon: savedQuery.last_run_at ? (
                            <Tooltip title="Materialized view">
                                <IconDatabase />
                            </Tooltip>
                        ) : (
                            <Tooltip title="View">
                                <IconDocument />
                            </Tooltip>
                        ),
                        searchMatch: matches
                            ? {
                                  matchingFields: matches.map((match) => match.key),
                                  nameHighlightRanges: matches.find((match) => match.key === 'name')?.indices,
                              }
                            : null,
                        onClick: () => {
                            multitabEditorLogic({
                                key: `hogQLQueryEditor/${router.values.location.pathname}`,
                            }).actions.editView(savedQuery.query.query, savedQuery)
                        },
                        menuItems: [
                            {
                                label: 'Open schema',
                                onClick: () => {
                                    actions.selectSchema(savedQuery)
                                },
                            },
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
                            {
                                label: 'Copy view name',
                                onClick: () => {
                                    void copyToClipboard(savedQuery.name)
                                },
                            },
                        ],
                    })),
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
                return activeScene === Scene.SQLEditor && sceneParams.params.id
                    ? ['saved-queries', parseInt(sceneParams.params.id)]
                    : null
            },
        ],
        dataWarehouseTablesBySourceType: [
            (s) => [s.dataWarehouseTables, s.posthogTables, s.databaseLoading],
            (
                dataWarehouseTables,
                posthogTables,
                databaseLoading
            ): BasicListItem[] | ExtendedListItem[] | ListItemAccordion[] => {
                const tablesBySourceType = dataWarehouseTables.reduce(
                    (acc: Record<string, DatabaseSchemaDataWarehouseTable[]>, table) => {
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

                const phTables = {
                    key: 'data-warehouse-tables',
                    noun: ['PostHog', 'PostHog'],
                    loading: databaseLoading,
                    icon: <DataWarehouseSourceIcon type="PostHog" sizePx={18} disableTooltip />,
                    items: posthogTables.map((table) => ({
                        key: table.id,
                        name: table.name,
                        url: '',
                        icon: <IconDatabase />,
                        searchMatch: null,
                        onClick: () => {
                            multitabEditorLogic({
                                key: `hogQLQueryEditor/${router.values.location.pathname}`,
                            }).actions.createTab(`SELECT * FROM ${table.name}`)
                        },
                        menuItems: [
                            {
                                label: 'Open schema',
                                onClick: () => {
                                    actions.selectSchema(table)
                                },
                            },
                            {
                                label: 'Add join',
                                onClick: () => {
                                    actions.selectSourceTable(table.name)
                                    actions.toggleJoinTableModal()
                                },
                            },
                            {
                                label: 'Copy table name',
                                onClick: () => {
                                    void copyToClipboard(table.name)
                                },
                            },
                        ],
                    })),
                } as ListItemAccordion

                const warehouseTables = Object.entries(tablesBySourceType).map(([sourceType, tables]) => ({
                    key: sourceType,
                    noun: [sourceType, sourceType],
                    icon: (
                        <DataWarehouseSourceIcon
                            type={
                                sourceType === 'Self-managed' && tables.length > 0
                                    ? mapUrlToProvider(tables[0].url_pattern)
                                    : sourceType
                            }
                            sizePx={18}
                            disableTooltip
                        />
                    ),
                    items: tables.map((table) => ({
                        key: table.id,
                        name: table.name,
                        url: '',
                        icon: <IconDatabase />,
                        searchMatch: null,
                        onClick: () => {
                            multitabEditorLogic({
                                key: `hogQLQueryEditor/${router.values.location.pathname}`,
                            }).actions.createTab(`SELECT * FROM ${table.name}`)
                        },
                        menuItems: [
                            {
                                label: 'Open schema',
                                onClick: () => {
                                    actions.selectSchema(table)
                                },
                            },
                            {
                                label: 'Add join',
                                onClick: () => {
                                    actions.selectSourceTable(table.name)
                                    actions.toggleJoinTableModal()
                                },
                            },
                            {
                                label: 'Copy table name',
                                onClick: () => {
                                    void copyToClipboard(table.name)
                                },
                            },
                        ],
                    })),
                })) as ListItemAccordion[]

                return [phTables, ...warehouseTables]
            },
        ],
        relevantDataWarehouseTables: [
            () => [navigation3000Logic.selectors.searchTerm],
            (searchTerm): [DatabaseSchemaDataWarehouseTable | DatabaseSchemaTable, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return dataWarehouseTablesfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return []
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
    })),
    subscriptions({
        allTables: (allTables: DatabaseSchemaTable[]) => {
            const tables = allTables.filter((n) => n.type === 'posthog' || n.type === 'data_warehouse')
            dataWarehouseTablesfuse.setCollection(tables)
        },
        dataWarehouseSavedQueries: (dataWarehouseSavedQueries) => {
            savedQueriesfuse.setCollection(dataWarehouseSavedQueries)
        },
    }),
])
