import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { Sorting } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { createFuse, Fuse } from 'lib/utils/fuseSearch'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { DatabaseSchemaDataWarehouseTable, FileSystemEntry } from '~/queries/schema/schema-general'
import {
    DataWarehouseViewLink,
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
} from '~/types'

import type { PaginatedResponse } from '../../../../../frontend/src/lib/api'
import type { DatabaseSchemaQueryResponse } from '../../../../../frontend/src/queries/schema/schema-general'
import type { ExternalDataSourceRevenueAnalyticsConfig } from '../../../../../frontend/src/types'
import type { SourceConfigResponseApi } from '../../../../warehouse_sources/frontend/generated/api.schemas'
import { availableSourcesLogic } from '../../scenes/NewSourceScene/availableSourcesLogic'
import { joinsDataLogic } from './joinsDataLogic'
import { sourcesDataLogic } from './sourcesDataLogic'

// Poll fast while something is actively syncing so sync status feels live; otherwise poll slowly. The
// list response can be very large (a source can have tens of thousands of schemas), so refetching it
// every 10s when nothing is changing wastes server work and can pile up behind slow requests. The idle
// cadence still bounds how long a server-started sync (scheduled, not user-triggered) takes to appear.
const REFRESH_INTERVAL = 10000
const IDLE_REFRESH_INTERVAL = 15000

const isActivelySyncing = (sources: PaginatedResponse<ExternalDataSource> | null): boolean =>
    (sources?.results ?? []).some(
        (source) =>
            source.status === ExternalDataJobStatus.Running ||
            (source.schemas ?? []).some((schema) => schema.status === ExternalDataSchemaStatus.Running)
    )

// Pages that actually render the sources list and want live sync-status updates. The 10s poll
// runs only on these. Every other page that mounts this logic (the new-source wizard, SQL editor,
// person/group profiles, debug, etc.) reads the sources once on mount without polling. This
// matters because the list response is large and was previously re-fetched every REFRESH_INTERVAL
// on pages that never display it.
const SOURCE_LIST_PATHS = [
    '/data-management/sources', // SourcesScene: managed, direct connect and self-managed sources tables
    '/data-management/revenue', // Revenue analytics settings: external source configuration
    '/settings/environment-marketing-analytics', // Marketing analytics settings: source configuration
]

const shouldPollSources = (): boolean => SOURCE_LIST_PATHS.includes(router.values.location.pathname)

export const SCHEMA_STATUS_ORDER: ExternalDataSchemaStatus[] = [
    ExternalDataSchemaStatus.Failed,
    ExternalDataSchemaStatus.Paused,
    ExternalDataSchemaStatus.Cancelled,
    ExternalDataSchemaStatus.Running,
    ExternalDataSchemaStatus.Completed,
]

// A starred source is a sidebar shortcut with this type, which gives it the Sources icon. The source id
// in `ref` keeps it apart from a star on the Sources page itself, because that shortcut has no ref.
const SOURCE_SHORTCUT_TYPE = 'data_source'

const sourceLabel = (
    source: ExternalDataSource,
    availableSources: Record<string, SourceConfigResponseApi> | null
): string => availableSources?.[source.source_type]?.label ?? source.source_type

export const totalRowsSynced = (source: ExternalDataSource): number =>
    source.schemas.reduce((acc, schema) => acc + (schema.table?.row_count ?? 0), 0)

// dayjs(undefined) is the current time, so a source that has never run needs its own value to sort as the oldest.
const lastRunTime = (source: ExternalDataSource): number =>
    source.last_run_at ? dayjs(source.last_run_at).valueOf() : 0

const worstSchemaStatusRank = (source: ExternalDataSource): number => {
    const statuses = new Set(source.schemas.filter((schema) => schema.should_sync).map((schema) => schema.status))
    const rank = SCHEMA_STATUS_ORDER.findIndex((status) => statuses.has(status))
    return rank === -1 ? SCHEMA_STATUS_ORDER.length : rank
}

// Keyed by the column keys in ManagedSourcesTable.
const MANAGED_SOURCE_COMPARATORS: Record<
    string,
    (
        a: ExternalDataSource,
        b: ExternalDataSource,
        availableSources: Record<string, SourceConfigResponseApi> | null
    ) => number
> = {
    name: (a, b, availableSources) =>
        sourceLabel(a, availableSources).localeCompare(sourceLabel(b, availableSources)) ||
        (a.prefix ?? '').localeCompare(b.prefix ?? ''),
    prefix: (a, b) => (a.prefix ?? '').localeCompare(b.prefix ?? ''),
    last_run_at: (a, b) => lastRunTime(a) - lastRunTime(b),
    rows_synced: (a, b) => totalRowsSynced(a) - totalRowsSynced(b),
    status: (a, b) => worstSchemaStatusRank(a) - worstSchemaStatusRank(b),
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sourceManagementLogicValues {
    availableSources: Record<string, SourceConfigResponseApi> | null // availableSourcesLogic
    dataWarehouseTables: DatabaseSchemaDataWarehouseTable[] // databaseTableListLogic
    database: Required<DatabaseSchemaQueryResponse> | null // databaseTableListLogic
    databaseLoading: boolean // databaseTableListLogic
    shortcutData: FileSystemEntry[] // projectTreeDataLogic
    shortcutDataLoading: boolean // projectTreeDataLogic
    dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null // sourcesDataLogic
    dataWarehouseSourcesLoading: boolean // sourcesDataLogic
    directSearchTerm: string
    directSources: ExternalDataSource[]
    filteredDirectSources: ExternalDataSource[]
    filteredManagedSources: ExternalDataSource[]
    filteredSelfManagedTables: DatabaseSchemaDataWarehouseTable[]
    hasZendeskSource: boolean
    managedSearchTerm: string
    managedSources: ExternalDataSource[]
    managedSourcesFuse: Fuse<ExternalDataSource>
    managedSourcesSorting: Sorting | null
    schemaReloadingById: Record<string, boolean>
    schemas: null
    schemasLoading: boolean
    searchTerm: string
    selfManagedTables: DatabaseSchemaDataWarehouseTable[]
    sortedManagedSources: ExternalDataSource[]
    sourceReloadingById: Record<string, boolean>
    starredSourceShortcuts: Record<string, FileSystemEntry>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sourceManagementLogicActions {
    ensureAllTableFields: () => {
        value: true
    } // databaseTableListLogic
    loadDatabase: (
        args_0?:
            | {
                  force?: boolean
                  shallow?: boolean
              }
            | undefined
    ) => {
        force?: boolean
        shallow?: boolean
    } // databaseTableListLogic
    deleteJoin: (join: DataWarehouseViewLink) => {
        join: DataWarehouseViewLink
    } // joinsDataLogic
    loadJoins: () => any // joinsDataLogic
    addShortcutItem: (item: FileSystemEntry) => {
        item: FileSystemEntry
    } // projectTreeDataLogic
    deleteShortcut: (id: string) => {
        id: string
    } // projectTreeDataLogic
    loadSources: () => {
        value: true
    } // sourcesDataLogic
    loadSourcesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // sourcesDataLogic
    loadSourcesSuccess: (
        dataWarehouseSources:
            | PaginatedResponse<ExternalDataSource>
            | {
                  count: number
                  next: null
                  previous: null
                  results: never[]
              },
        payload?:
            | {
                  value: true
              }
            | undefined
    ) => {
        dataWarehouseSources:
            | PaginatedResponse<ExternalDataSource>
            | {
                  count: number
                  next: null
                  previous: null
                  results: never[]
              }
        payload?: {
            value: true
        }
    } // sourcesDataLogic
    updateSource: (source: ExternalDataSource) => ExternalDataSource // sourcesDataLogic
    updateSourceRevenueAnalyticsConfig: (args_0: {
        config: Partial<ExternalDataSourceRevenueAnalyticsConfig>
        source: ExternalDataSource
    }) => {
        config: Partial<ExternalDataSourceRevenueAnalyticsConfig>
        source: ExternalDataSource
    } // sourcesDataLogic
    deleteSelfManagedTable: (tableId: string) => {
        tableId: string
    }
    deleteSource: (source: ExternalDataSource) => {
        source: ExternalDataSource
    }
    refreshSelfManagedTableSchema: (tableId: string) => {
        tableId: string
    }
    reloadSource: (source: ExternalDataSource) => {
        source: ExternalDataSource
    }
    schemaLoadingFinished: (schema: ExternalDataSourceSchema) => {
        schema: ExternalDataSourceSchema
    }
    setDirectSearchTerm: (directSearchTerm: string) => {
        directSearchTerm: string
    }
    setManagedSearchTerm: (managedSearchTerm: string) => {
        managedSearchTerm: string
    }
    setManagedSourcesSorting: (sorting: Sorting | null) => {
        sorting: Sorting | null
    }
    setSearchTerm: (searchTerm: string) => {
        searchTerm: string
    }
    sourceLoadingFinished: (source: ExternalDataSource) => {
        source: ExternalDataSource
    }
    toggleSourceStarred: (source: ExternalDataSource) => {
        source: ExternalDataSource
    }
    updateSchema: (schema: ExternalDataSourceSchema) => ExternalDataSourceSchema
    updateSchemaFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    updateSchemaSuccess: (
        schemas: null,
        payload?: ExternalDataSourceSchema
    ) => {
        schemas: null
        payload?: ExternalDataSourceSchema
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface sourceManagementLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        selfManagedTables: (
            dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]
        ) => DatabaseSchemaDataWarehouseTable[]
        filteredSelfManagedTables: (
            selfManagedTables: DatabaseSchemaDataWarehouseTable[],
            searchTerm: string
        ) => DatabaseSchemaDataWarehouseTable[]
        managedSources: (dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null) => ExternalDataSource[]
        directSources: (dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null) => ExternalDataSource[]
        filteredDirectSources: (directSources: ExternalDataSource[], directSearchTerm: string) => ExternalDataSource[]
        managedSourcesFuse: (
            managedSources: ExternalDataSource[],
            availableSources: Record<string, SourceConfigResponseApi> | null
        ) => Fuse<ExternalDataSource>
        filteredManagedSources: (
            managedSources: ExternalDataSource[],
            managedSourcesFuse: Fuse<ExternalDataSource>,
            managedSearchTerm: string
        ) => ExternalDataSource[]
        starredSourceShortcuts: (shortcutData: any) => Record<string, FileSystemEntry>
        sortedManagedSources: (
            filteredManagedSources: ExternalDataSource[],
            managedSourcesSorting: any,
            starredSourceShortcuts: any,
            managedSearchTerm: string,
            availableSources: Record<string, SourceConfigResponseApi> | null
        ) => ExternalDataSource[]
        hasZendeskSource: (dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null) => boolean
    }
}

export type sourceManagementLogicType = MakeLogicType<
    sourceManagementLogicValues,
    sourceManagementLogicActions,
    Record<string, any>,
    sourceManagementLogicMeta
>

export const sourceManagementLogic = kea<sourceManagementLogicType>([
    path(['products', 'dataWarehouse', 'sourceManagementLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['database', 'databaseLoading', 'dataWarehouseTables'],
            sourcesDataLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading'],
            availableSourcesLogic,
            ['availableSources'],
            projectTreeDataLogic,
            ['shortcutData', 'shortcutDataLoading'],
        ],
        actions: [
            databaseTableListLogic,
            ['ensureAllTableFields', 'loadDatabase'],
            joinsDataLogic,
            ['loadJoins', 'deleteJoin'],
            sourcesDataLogic,
            [
                'loadSources',
                'loadSourcesSuccess',
                'loadSourcesFailure',
                'updateSource',
                'updateSourceRevenueAnalyticsConfig',
            ],
            projectTreeDataLogic,
            ['addShortcutItem', 'deleteShortcut'],
        ],
    })),
    actions({
        deleteSource: (source: ExternalDataSource) => ({ source }),
        reloadSource: (source: ExternalDataSource) => ({ source }),
        sourceLoadingFinished: (source: ExternalDataSource) => ({ source }),
        schemaLoadingFinished: (schema: ExternalDataSourceSchema) => ({ schema }),
        deleteSelfManagedTable: (tableId: string) => ({ tableId }),
        refreshSelfManagedTableSchema: (tableId: string) => ({ tableId }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setManagedSearchTerm: (managedSearchTerm: string) => ({ managedSearchTerm }),
        setDirectSearchTerm: (directSearchTerm: string) => ({ directSearchTerm }),
        setManagedSourcesSorting: (sorting: Sorting | null) => ({ sorting }),
        toggleSourceStarred: (source: ExternalDataSource) => ({ source }),
    }),
    loaders(({ actions, values }) => ({
        schemas: [
            null,
            {
                updateSchema: async (schema: ExternalDataSourceSchema) => {
                    // Optimistic UI updates before sending updates to the backend
                    const clonedSources = JSON.parse(
                        JSON.stringify(values.dataWarehouseSources?.results ?? [])
                    ) as ExternalDataSource[]
                    const sourceIndex = clonedSources.findIndex((n) => n.schemas?.find((m) => m.id === schema.id))
                    if (sourceIndex !== -1) {
                        const schemaIndex = clonedSources[sourceIndex].schemas.findIndex((n) => n.id === schema.id)
                        clonedSources[sourceIndex].schemas[schemaIndex] = schema

                        actions.loadSourcesSuccess({
                            ...values.dataWarehouseSources,
                            results: clonedSources,
                        })
                    }

                    await api.externalDataSchemas.update(schema.id, schema)
                    actions.loadSources()

                    return null
                },
            },
        ],
    })),
    reducers(() => ({
        sourceReloadingById: [
            {} as Record<string, boolean>,
            {
                reloadSource: (state, { source }) => ({
                    ...state,
                    [source.id]: true,
                }),
                deleteSource: (state, { source }) => ({
                    ...state,
                    [source.id]: true,
                }),
                sourceLoadingFinished: (state, { source }) => ({
                    ...state,
                    [source.id]: false,
                }),
            },
        ],
        schemaReloadingById: [
            {} as Record<string, boolean>,
            {
                schemaLoadingFinished: (state, { schema }) => ({
                    ...state,
                    [schema.id]: false,
                }),
            },
        ],
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        managedSearchTerm: [
            '' as string,
            {
                setManagedSearchTerm: (_, { managedSearchTerm }) => managedSearchTerm,
            },
        ],
        directSearchTerm: [
            '' as string,
            {
                setDirectSearchTerm: (_, { directSearchTerm }) => directSearchTerm,
            },
        ],
        managedSourcesSorting: [
            null as Sorting | null,
            {
                setManagedSourcesSorting: (_, { sorting }) => sorting,
            },
        ],
    })),
    selectors({
        selfManagedTables: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables: DatabaseSchemaDataWarehouseTable[]): DatabaseSchemaDataWarehouseTable[] => {
                return dataWarehouseTables.filter((table) => !table.source)
            },
        ],
        filteredSelfManagedTables: [
            (s) => [s.selfManagedTables, s.searchTerm],
            (
                selfManagedTables: DatabaseSchemaDataWarehouseTable[],
                searchTerm: string
            ): DatabaseSchemaDataWarehouseTable[] => {
                if (!searchTerm?.trim()) {
                    return selfManagedTables
                }
                const normalizedSearch = searchTerm.toLowerCase()
                return selfManagedTables.filter((table) => table.name.toLowerCase().includes(normalizedSearch))
            },
        ],
        managedSources: [
            (s) => [s.dataWarehouseSources],
            (
                dataWarehouseSources: null | import('lib/api').PaginatedResponse<ExternalDataSource>
            ): ExternalDataSource[] =>
                (dataWarehouseSources?.results ?? []).filter(
                    (source) => source.access_method?.toLowerCase() !== 'direct'
                ),
        ],
        directSources: [
            (s) => [s.dataWarehouseSources],
            (
                dataWarehouseSources: null | import('lib/api').PaginatedResponse<ExternalDataSource>
            ): ExternalDataSource[] =>
                (dataWarehouseSources?.results ?? []).filter(
                    (source) => source.access_method?.toLowerCase() === 'direct'
                ),
        ],
        filteredDirectSources: [
            (s) => [s.directSources, s.directSearchTerm],
            (directSources: ExternalDataSource[], directSearchTerm: string): ExternalDataSource[] => {
                const normalizedSearch = directSearchTerm?.trim().toLowerCase()
                if (!normalizedSearch) {
                    return directSources
                }
                return directSources.filter(
                    (source) =>
                        source.source_type.toLowerCase().includes(normalizedSearch) ||
                        source.prefix?.toLowerCase().includes(normalizedSearch) ||
                        source.description?.toLowerCase().includes(normalizedSearch)
                )
            },
        ],
        // Search the display label as well as the internal source_type. Fuzzy, like the source catalog.
        managedSourcesFuse: [
            (s) => [s.managedSources, s.availableSources],
            (
                managedSources: ExternalDataSource[],
                availableSources: Record<string, SourceConfigResponseApi> | null
            ): Fuse<ExternalDataSource> =>
                createFuse(managedSources, {
                    keys: [
                        {
                            name: 'label',
                            getFn: (source) => sourceLabel(source, availableSources),
                        },
                        'source_type',
                        'prefix',
                        'description',
                    ],
                }),
        ],
        filteredManagedSources: [
            (s) => [s.managedSources, s.managedSourcesFuse, s.managedSearchTerm],
            (
                managedSources: ExternalDataSource[],
                managedSourcesFuse: Fuse<ExternalDataSource>,
                managedSearchTerm: string
            ): ExternalDataSource[] => {
                const trimmed = managedSearchTerm?.trim()
                if (!trimmed) {
                    return managedSources
                }
                return managedSourcesFuse.search(trimmed).map((r) => r.item)
            },
        ],
        starredSourceShortcuts: [
            (s) => [s.shortcutData],
            (shortcutData: FileSystemEntry[]): Record<string, FileSystemEntry> =>
                Object.fromEntries(
                    shortcutData
                        .filter((shortcut) => shortcut.type === SOURCE_SHORTCUT_TYPE && !!shortcut.ref)
                        .map((shortcut) => [shortcut.ref as string, shortcut])
                ),
        ],
        sortedManagedSources: [
            (s) => [
                s.filteredManagedSources,
                s.managedSourcesSorting,
                s.starredSourceShortcuts,
                s.managedSearchTerm,
                s.availableSources,
            ],
            (
                filteredManagedSources: ExternalDataSource[],
                managedSourcesSorting: Sorting | null,
                starredSourceShortcuts: Record<string, FileSystemEntry>,
                managedSearchTerm: string,
                availableSources: Record<string, SourceConfigResponseApi> | null
            ): ExternalDataSource[] => {
                const comparator = managedSourcesSorting
                    ? MANAGED_SOURCE_COMPARATORS[managedSourcesSorting.columnKey]
                    : undefined
                const sorted =
                    managedSourcesSorting && comparator
                        ? [...filteredManagedSources].sort(
                              (a, b) => managedSourcesSorting.order * comparator(a, b, availableSources)
                          )
                        : filteredManagedSources
                // While searching, starred sources do not float above better matches.
                if (managedSearchTerm?.trim()) {
                    return sorted
                }
                return [
                    ...sorted.filter((source) => starredSourceShortcuts[source.id]),
                    ...sorted.filter((source) => !starredSourceShortcuts[source.id]),
                ]
            },
        ],
        hasZendeskSource: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources: null | import('lib/api').PaginatedResponse<ExternalDataSource>): boolean => {
                const sources = dataWarehouseSources?.results
                if (!sources) {
                    return false
                }

                return !!sources.some((source) => source?.source_type === 'Zendesk')
            },
        ],
    }),
    urlToAction(({ actions }) => {
        // Reload (and restart polling) when landing on a page that renders the sources list, in
        // case this shared logic was already mounted by another scene and afterMount won't re-run.
        // Skip same-path URL changes — the sources tables sync their pagination to the URL (e.g.
        // ?managed-sources_page=2), and a full refetch on every page click would blink the table
        // and shift the page.
        const reload = (
            _params: Record<string, string | undefined>,
            _searchParams: Record<string, any>,
            _hashParams: Record<string, any>,
            currentLocation: { pathname: string; initial?: boolean },
            previousLocation?: { pathname: string }
        ): void => {
            if (!currentLocation.initial && currentLocation.pathname === previousLocation?.pathname) {
                return
            }
            actions.loadSources()
        }
        return Object.fromEntries(SOURCE_LIST_PATHS.map((sourcePath) => [sourcePath, reload]))
    }),
    listeners(({ actions, values, cache }) => ({
        deleteSelfManagedTable: async ({ tableId }) => {
            await api.dataWarehouseTables.delete(tableId)
            actions.loadDatabase()
        },
        refreshSelfManagedTableSchema: async ({ tableId }) => {
            lemonToast.info('Updating schema...')
            await api.dataWarehouseTables.refreshSchema(tableId)
            lemonToast.success('Schema updated')
            actions.loadDatabase()
        },
        deleteSource: async ({ source }) => {
            // The confirm dialog stays clickable while it animates out, so a double click sends the
            // delete twice. The second request 404s on a source the first one already removed, which
            // surfaces as a failure for something that worked.
            const deleting: Set<string> = (cache.deletingSourceIds ??= new Set())
            if (deleting.has(source.id)) {
                return
            }
            deleting.add(source.id)

            try {
                await api.externalDataSources.delete(source.id)
                // Only on success: a transient list failure resolves to an empty page, so reloading
                // after a delete that failed offline would blank a list of sources that still exist.
                actions.loadSources()
                posthog.capture('source deleted', { sourceType: source.source_type })
                // The backend removes shortcuts only for items in the file system, and sources are not
                // in it, so a star would otherwise stay in the sidebar and link to a deleted source.
                const shortcut = values.starredSourceShortcuts[source.id]
                if (shortcut) {
                    actions.deleteShortcut(shortcut.id)
                }
            } catch (e) {
                lemonToast.error("We couldn't delete this source. Refresh the page and try again.")
                posthog.captureException(e)
            } finally {
                deleting.delete(source.id)
                actions.sourceLoadingFinished(source)
            }
        },
        reloadSource: async ({ source }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSources = JSON.parse(
                JSON.stringify(values.dataWarehouseSources?.results ?? [])
            ) as ExternalDataSource[]
            const sourceIndex = clonedSources.findIndex((n) => n.id === source.id)
            clonedSources[sourceIndex].status = ExternalDataJobStatus.Running
            clonedSources[sourceIndex].schemas = clonedSources[sourceIndex].schemas.map((n) => {
                if (n.should_sync) {
                    return {
                        ...n,
                        status: ExternalDataSchemaStatus.Running,
                    }
                }

                return n
            })

            actions.loadSourcesSuccess({
                ...values.dataWarehouseSources,
                results: clonedSources,
            })

            try {
                await api.externalDataSources.reload(source.id)
                actions.loadSources()

                posthog.capture('source reloaded', { sourceType: source.source_type })
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant refresh source at this time')
                }
            }
            actions.sourceLoadingFinished(source)
        },
        updateSchema: (schema) => {
            posthog.capture('schema updated', { shouldSync: schema.should_sync, syncType: schema.sync_type })
        },
        toggleSourceStarred: ({ source }) => {
            const shortcut = values.starredSourceShortcuts[source.id]
            if (shortcut) {
                actions.deleteShortcut(shortcut.id)
                return
            }
            const label = sourceLabel(source, values.availableSources)
            actions.addShortcutItem({
                id: source.id,
                path: escapePath(source.prefix ? `${label} (${source.prefix})` : label),
                type: SOURCE_SHORTCUT_TYPE,
                ref: source.id,
                href: urls.dataWarehouseSource(`managed-${source.id}`),
            })
        },
        setManagedSourcesSorting: ({ sorting }) => {
            if (sorting) {
                posthog.capture('managed sources sorted', { columnKey: sorting.columnKey, order: sorting.order })
            }
        },
        loadSourcesSuccess: ({ dataWarehouseSources }) => {
            if (shouldPollSources()) {
                // Poll fast while a sync is in progress, slowly otherwise.
                const interval = isActivelySyncing(dataWarehouseSources) ? REFRESH_INTERVAL : IDLE_REFRESH_INTERVAL
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        // Re-check at fire time: this shared logic stays mounted across navigation
                        // and the timeout is only disposed on unmount, so skip the refresh if the
                        // user has since left a page that displays the sources list.
                        if (shouldPollSources()) {
                            actions.loadSources()
                        }
                    }, interval)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
        loadSourcesFailure: () => {
            if (shouldPollSources()) {
                // Nothing loaded to inspect; back off to the slow cadence rather than hammering on errors.
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        if (shouldPollSources()) {
                            actions.loadSources()
                        }
                    }, IDLE_REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.databaseLoading) {
            if (!values.database) {
                actions.loadDatabase()
            } else {
                actions.ensureAllTableFields()
            }
        }
        actions.loadSources()
    }),
    beforeUnmount(() => {
        // Disposables plugin handles cleanup automatically
    }),
])
