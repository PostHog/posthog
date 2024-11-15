import Fuse from 'fuse.js'
import { connect, kea, path, selectors } from 'kea'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
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
        ],
        actions: [editorSceneLogic, ['selectSchema'], dataWarehouseViewsLogic, ['deleteDataWarehouseSavedQuery']],
    }),
    selectors(({ actions }) => ({
        contents: [
            (s) => [
                s.relevantSavedQueries,
                s.dataWarehouseSavedQueriesLoading,
                s.relevantPosthogTables,
                s.relevantDataWarehouseTables,
                s.databaseLoading,
            ],
            (
                relevantSavedQueries,
                dataWarehouseSavedQueriesLoading,
                relevantPosthogTables,
                relevantDataWarehouseTables,
                databaseLoading
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
                    })),
                } as SidebarCategory,
                {
                    key: 'data-warehouse-views',
                    noun: ['view', 'views'],
                    loading: dataWarehouseSavedQueriesLoading,
                    items: relevantSavedQueries.map(([savedQuery, matches]) => ({
                        key: savedQuery.id,
                        name: savedQuery.name,
                        url: '',
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
                                    }).actions.createTab(savedQuery.query.query, savedQuery)
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
            ],
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
