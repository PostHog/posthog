import Fuse from 'fuse.js'
import { actions, connect, events, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { IconCalculate, IconClipboardEdit } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { FuseSearchMatch } from '~/layout/navigation-3000/sidebars/utils'
import { BasicListItem, ExtendedListItem, ListItemAccordion, SidebarCategory } from '~/layout/navigation-3000/types'
import { DatabaseSchemaTableCommon } from '~/queries/schema/schema-general'
import { DataWarehouseFolder, DataWarehouseSavedQuery, PipelineTab } from '~/types'

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

export const TEMPORARY_FOLDER_KEY = '$__temp__$'

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
    actions({
        setTemporaryFolder: (folder: { parentId: string | null } | null) => ({ folder }),
    }),
    reducers({
        temporaryFolder: [
            null as { parentId: string | null } | null,
            {
                setTemporaryFolder: (_, { folder }) => folder,
            },
        ],
    }),
    loaders(({ values }) => ({
        folders: [
            [] as DataWarehouseFolder[],
            {
                loadFolders: async () => {
                    const response = await api.dataWarehouseFolders.list()
                    return response.results
                },
                addFolder: async ({ name, parentId }) => {
                    const folder = await api.dataWarehouseFolders.create({ name, parent: parentId })
                    return values.folders.concat(folder)
                },
                deleteFolder: async ({ id }) => {
                    await api.dataWarehouseFolders.delete(id)
                    return values.folders.filter((folder) => folder.id !== id)
                },
                renameFolder: async ({ id, name }) => {
                    const _folder = await api.dataWarehouseFolders.update(id, { name })
                    return values.folders.map((folder) => (folder.id === id ? _folder : folder))
                },
                moveViewToFolder: async ({ viewId, toFolderId }) => {
                    let newFolders = [...values.folders]

                    const fromFolder = values.folders.find((folder) => folder.items.includes(viewId))
                    const toFolder = values.folders.find((folder) => folder.id === toFolderId)

                    if (fromFolder?.id === toFolder?.id) {
                        return newFolders
                    }

                    if (fromFolder) {
                        const fromFolderNew = await api.dataWarehouseFolders.update(fromFolder.id, {
                            items: fromFolder.items.filter((id) => id !== viewId),
                        })
                        newFolders = newFolders.map((folder) => (folder.id === fromFolder.id ? fromFolderNew : folder))
                    }

                    if (toFolder) {
                        const toFolderNew = await api.dataWarehouseFolders.update(toFolder.id, {
                            items: [...toFolder.items, viewId],
                        })
                        newFolders = newFolders.map((folder) => (folder.id === toFolder.id ? toFolderNew : folder))
                    }

                    return newFolders
                },
            },
        ],
    })),
    selectors(({ actions }) => ({
        isFolder: [
            (s) => [s.folders],
            (folders) => {
                return (id: string) => {
                    return folders.some((folder) => folder.id === id)
                }
            },
        ],
        contents: [
            (s) => [
                s.dataWarehouseSavedQueries,
                s.relevantSavedQueries,
                s.initialDataWarehouseSavedQueryLoading,
                s.relevantSources,
                s.dataWarehouseTablesBySourceType,
                s.databaseLoading,
                s.folders,
                s.temporaryFolder,
            ],
            (
                dataWarehouseSavedQueries,
                relevantSavedQueries,
                initialDataWarehouseSavedQueryLoading,
                relevantSources,
                dataWarehouseTablesBySourceType,
                databaseLoading,
                folders,
                temporaryFolder
            ) => {
                // Helper to build nested folder structure
                const buildFolderTree = (parentId: string | null = null): ListItemAccordion[] => {
                    const regularFolders = folders
                        .filter((folder) => folder.parent === parentId)
                        .map((folder) => {
                            const folderItems = folder.items
                                .map((itemId: string) => {
                                    const savedQuery = dataWarehouseSavedQueries.find((q) => q.id === itemId)
                                    if (!savedQuery) {
                                        return null
                                    }
                                    return {
                                        key: savedQuery.id,
                                        name: savedQuery.name,
                                        url: '',
                                        icon: savedQuery.status ? <IconCalculate /> : <IconClipboardEdit />,
                                        onClick: () => {
                                            editorSceneLogic.actions.selectSchema(savedQuery)
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
                                                    viewLinkLogic.actions.selectSourceTable(savedQuery.name)
                                                    viewLinkLogic.actions.toggleJoinTableModal()
                                                },
                                            },
                                            {
                                                label: 'Delete',
                                                status: 'danger',
                                                onClick: () => {
                                                    dataWarehouseViewsLogic.actions.deleteDataWarehouseSavedQuery(
                                                        savedQuery.id
                                                    )
                                                },
                                            },
                                        ],
                                        draggable: true,
                                    } as BasicListItem
                                })
                                .filter((item): item is BasicListItem => item !== null)

                            return {
                                key: folder.id,
                                name: folder.name,
                                noun: ['folder', 'folders'],
                                onRename: async (newName: string) =>
                                    actions.renameFolder({ id: folder.id, name: newName }),
                                menuItems: [
                                    {
                                        label: 'Add folder',
                                        onClick: () => {
                                            actions.setTemporaryFolder({ parentId: folder.id })
                                        },
                                    },
                                    {
                                        label: 'Delete folder',
                                        status: 'danger',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: 'Delete folder',
                                                content:
                                                    'Are you sure you want to delete this folder? (folder contents will not be deleted)',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    onClick: () => actions.deleteFolder({ id: folder.id }),
                                                    status: 'danger',
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        },
                                    },
                                ],
                                items: [...buildFolderTree(folder.id), ...folderItems],
                            } as ListItemAccordion
                        })

                    if (temporaryFolder && temporaryFolder.parentId === parentId) {
                        regularFolders.push({
                            key: TEMPORARY_FOLDER_KEY,
                            name: '',
                            noun: ['folder', 'folders'],
                            items: [],
                            onRename: async (newName: string) => {
                                if (newName.trim()) {
                                    actions.addFolder({ name: newName, parentId: temporaryFolder.parentId })
                                }
                                actions.setTemporaryFolder(null)
                            },
                            onCancelRename: () => {
                                actions.setTemporaryFolder(null)
                            },
                        } as ListItemAccordion)
                    }

                    return regularFolders
                }

                return [
                    {
                        key: 'data-warehouse-views',
                        noun: ['view', 'views'],
                        loading: initialDataWarehouseSavedQueryLoading,
                        menuItems: [
                            {
                                label: 'Add folder',
                                onClick: () => {
                                    actions.setTemporaryFolder({ parentId: null })
                                },
                            },
                        ],
                        items:
                            relevantSavedQueries.length > 0
                                ? [
                                      ...relevantSavedQueries.map(([savedQuery, matches]) => ({
                                          key: savedQuery.id,
                                          name: savedQuery.name,
                                          url: '',
                                          searchMatch: matches,
                                          onClick: () => {
                                              editorSceneLogic.actions.selectSchema(savedQuery)
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
                                                      viewLinkLogic.actions.selectSourceTable(savedQuery.name)
                                                      viewLinkLogic.actions.toggleJoinTableModal()
                                                  },
                                              },
                                              {
                                                  label: 'Delete',
                                                  status: 'danger',
                                                  onClick: () => {
                                                      dataWarehouseViewsLogic.actions.deleteDataWarehouseSavedQuery(
                                                          savedQuery.id
                                                      )
                                                  },
                                              },
                                          ],
                                      })),
                                  ]
                                : [
                                      ...buildFolderTree(),
                                      ...(dataWarehouseSavedQueries
                                          .filter(
                                              (savedQuery) =>
                                                  !folders.some((folder) => folder.items.includes(savedQuery.id))
                                          )
                                          .map((savedQuery) => ({
                                              key: savedQuery.id,
                                              name: savedQuery.name,
                                              url: '',
                                              icon: savedQuery.last_run_at ? <IconCalculate /> : <IconClipboardEdit />,
                                              onClick: () => {
                                                  editorSceneLogic.actions.selectSchema(savedQuery)
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
                                                          viewLinkLogic.actions.selectSourceTable(savedQuery.name)
                                                          viewLinkLogic.actions.toggleJoinTableModal()
                                                      },
                                                  },
                                                  {
                                                      label: 'Delete',
                                                      status: 'danger',
                                                      onClick: () => {
                                                          dataWarehouseViewsLogic.actions.deleteDataWarehouseSavedQuery(
                                                              savedQuery.id
                                                          )
                                                      },
                                                  },
                                              ],
                                              draggable: true,
                                          })) as BasicListItem[]),
                                  ],
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
                                                nameHighlightRanges: matches.find((match) => match.key === 'name')
                                                    ?.indices,
                                            }
                                          : null,
                                      onClick: () => {
                                          editorSceneLogic.actions.selectSchema(table)
                                      },
                                      menuItems: [
                                          {
                                              label: 'Add join',
                                              onClick: () => {
                                                  viewLinkLogic.actions.selectSourceTable(table.name)
                                                  viewLinkLogic.actions.toggleJoinTableModal()
                                              },
                                          },
                                      ],
                                  }))
                                : dataWarehouseTablesBySourceType,
                        onAdd: () => {
                            router.actions.push(urls.pipeline(PipelineTab.Sources))
                        },
                    } as SidebarCategory,
                ]
            },
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
                            editorSceneLogic.actions.selectSchema(table)
                        },
                        menuItems: [
                            {
                                label: 'Add join',
                                onClick: () => {
                                    viewLinkLogic.actions.selectSourceTable(table.name)
                                    viewLinkLogic.actions.toggleJoinTableModal()
                                },
                            },
                        ],
                    })),
                })) as ListItemAccordion[]
            },
        ],
        relevantSavedQueries: [
            () => [navigation3000Logic.selectors.searchTerm],
            (searchTerm): [DataWarehouseSavedQuery, FuseSearchMatch[] | null][] => {
                if (searchTerm) {
                    return savedQueriesfuse
                        .search(searchTerm)
                        .map((result) => [result.item, result.matches as FuseSearchMatch[]])
                }
                return []
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
    events(({ actions }) => ({
        afterMount() {
            actions.loadFolders()
        },
    })),
])
