import { MakeLogicType, actions, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { ApiConfig } from 'lib/api'
import type { PaginatedResponse } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { type FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { ExternalDataSource } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconClickHouse from 'public/services/clickhouse.png'
import IconDuckDB from 'public/services/duckdb.svg'
import IconMotherDuck from 'public/services/motherduck.png'
import IconMySQL from 'public/services/mysql.png'
import IconPostgres from 'public/services/postgres.png'
import IconRedshift from 'public/services/redshift.png'
import IconSnowflake from 'public/services/snowflake.png'
import IconTrino from 'public/services/trino.svg'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import {
    externalDataSourcesConnectionsList,
    externalDataSourcesDirectConnectionOptionsList,
} from 'products/warehouse_sources/frontend/generated/api'
import type {
    DirectConnectionSourceOptionApi,
    ExternalDataSourceConnectionOptionApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
// A direct-connection menu item's value is this prefix + the source type (e.g. '...:Postgres').
export const ADD_DIRECT_CONNECTION_PREFIX = '__add_direct_connection__:'
export const CONFIGURE_SOURCES = '__configure_sources__'

export interface ConnectionSelectorConfig {
    allowedEngines?: string[]
    requireHogQL?: boolean
    showSourceActions?: boolean
}

export interface ConnectionSelectOption {
    // A leaf carries a `value`; a node carries nested `options` and renders as a submenu.
    value?: string
    label: string
    disabled?: boolean
    disabledReason?: string
    hidden?: boolean
    iconSrc?: string
    managementUrl?: string
    options?: ConnectionSelectOption[]
}

export interface ConnectionSelectOptionGroup {
    options: ConnectionSelectOption[]
}

type ConnectionEngine =
    | 'duckdb'
    | 'postgres'
    | 'mysql'
    | 'snowflake'
    | 'redshift'
    | 'clickhouse'
    | 'motherduck'
    | 'trino'

const ENGINE_LABELS: Record<ConnectionEngine, string> = {
    duckdb: 'DuckDB',
    postgres: 'Postgres',
    mysql: 'MySQL',
    snowflake: 'Snowflake',
    redshift: 'Redshift',
    clickhouse: 'ClickHouse',
    motherduck: 'MotherDuck',
    trino: 'Trino',
}

const ENGINE_ICONS: Record<ConnectionEngine, string> = {
    duckdb: IconDuckDB,
    postgres: IconPostgres,
    mysql: IconMySQL,
    snowflake: IconSnowflake,
    redshift: IconRedshift,
    clickhouse: IconClickHouse,
    motherduck: IconMotherDuck,
    trino: IconTrino,
}

function getConnectionEngine(
    source: Pick<ExternalDataSourceConnectionOptionApi, 'engine' | 'source_type'>
): ConnectionEngine {
    if (
        source.engine === 'duckdb' ||
        source.engine === 'mysql' ||
        source.engine === 'snowflake' ||
        source.engine === 'redshift' ||
        source.engine === 'clickhouse' ||
        source.engine === 'motherduck' ||
        source.engine === 'trino'
    ) {
        return source.engine
    }
    // Synced sources have no detected connection engine — derive it from the source type.
    const sourceTypeEngine = source.source_type?.toLowerCase()
    if (sourceTypeEngine && sourceTypeEngine in ENGINE_LABELS) {
        return sourceTypeEngine as ConnectionEngine
    }
    return 'postgres'
}

export function getConnectionOptionLabel(source: ExternalDataSourceConnectionOptionApi): string {
    const engine = getConnectionEngine(source)
    if (isManagedWarehouseConnection(source)) {
        return 'PostHog (Managed warehouse)'
    }
    const isSynced = source.access_method === 'warehouse'
    // Prefer the user-set description, then the prefix; fall back to the source type name (never the raw UUID).
    const name = source.description || source.prefix || source.source_type || source.id
    return `${name} (${ENGINE_LABELS[engine]}${isSynced ? ' · synced' : ''})`
}

function isManagedWarehouseConnection(source: ExternalDataSourceConnectionOptionApi): boolean {
    return source.is_builtin_managed_warehouse
}

export function getConnectionSelectorValue(
    connectionOptionsLoading: boolean,
    selectedConnectionId: string | undefined
): string {
    if (connectionOptionsLoading) {
        return LOADING_CONNECTIONS
    }

    if (selectedConnectionId) {
        return selectedConnectionId
    }

    return POSTHOG_WAREHOUSE
}

export function addHiddenSelectedConnectionOption(
    optionGroups: ConnectionSelectOptionGroup[],
    connectionOptions: ExternalDataSourceConnectionOptionApi[] | null,
    connectionOptionsLoading: boolean,
    selectedConnectionId: string | undefined
): ConnectionSelectOptionGroup[] {
    if (
        connectionOptionsLoading ||
        !selectedConnectionId ||
        (connectionOptions ?? []).some((source) => source.id === selectedConnectionId)
    ) {
        return optionGroups
    }

    const [sourceGroup, ...remainingGroups] = optionGroups
    if (!sourceGroup) {
        return optionGroups
    }

    return [
        {
            ...sourceGroup,
            options: [
                ...sourceGroup.options,
                {
                    value: selectedConnectionId,
                    label: 'Selected connection (hidden)',
                    hidden: true,
                },
            ],
        },
        ...remainingGroups,
    ]
}

export function isConnectionSelectorRestricted(config?: ConnectionSelectorConfig): boolean {
    return config?.allowedEngines !== undefined || !!config?.requireHogQL || config?.showSourceActions === false
}

export function getConnectionSelectOptions(
    optionGroups: ConnectionSelectOptionGroup[],
    connectionOptions: ExternalDataSourceConnectionOptionApi[] | null,
    connectionOptionsLoading: boolean,
    selectedConnectionId: string | undefined,
    config?: ConnectionSelectorConfig
): ConnectionSelectOptionGroup[] {
    if (!isConnectionSelectorRestricted(config)) {
        return addHiddenSelectedConnectionOption(
            optionGroups,
            connectionOptions,
            connectionOptionsLoading,
            selectedConnectionId
        )
    }

    const allowedSources = (connectionOptions ?? []).filter(
        (source) =>
            !source.is_builtin_managed_warehouse &&
            (!config?.allowedEngines || (!!source.engine && config.allowedEngines.includes(source.engine))) &&
            (!config?.requireHogQL || source.supports_hogql === true)
    )
    const options = (optionGroups[0]?.options ?? []).flatMap((option) => {
        if (option.value === POSTHOG_WAREHOUSE || option.value === LOADING_CONNECTIONS) {
            return [option]
        }
        if (!allowedSources.some((source) => source.id === option.value)) {
            return []
        }
        const { managementUrl: _managementUrl, ...connectionOption } = option
        return [connectionOption]
    })
    if (connectionOptions === null && !options.some((option) => option.value === LOADING_CONNECTIONS)) {
        options.push({ value: LOADING_CONNECTIONS, label: 'Loading...', disabled: true })
    }

    if (
        !connectionOptionsLoading &&
        connectionOptions !== null &&
        selectedConnectionId &&
        !options.some((option) => option.value === selectedConnectionId)
    ) {
        const selectedSource = connectionOptions?.find((source) => source.id === selectedConnectionId)
        options.push({
            value: selectedConnectionId,
            label: selectedSource
                ? `${getConnectionOptionLabel(selectedSource)} (unavailable)`
                : 'Selected connection (unavailable)',
            disabled: true,
            disabledReason: 'This connection is unavailable or unsupported. Choose another connection.',
        })
    }

    return [{ options }]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface connectionSelectorLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    connectionOptions: ExternalDataSourceConnectionOptionApi[] | null
    connectionOptionsLoading: boolean
    connectionSelectOptions: ConnectionSelectOptionGroup[]
    directConnectionOptions: DirectConnectionSourceOptionApi[] | null
    directConnectionOptionsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface connectionSelectorLogicActions {
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
    loadConnectionOptions: () => any
    loadConnectionOptionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadConnectionOptionsSuccess: (
        connectionOptions: ExternalDataSourceConnectionOptionApi[],
        payload?: any
    ) => {
        connectionOptions: ExternalDataSourceConnectionOptionApi[]
        payload?: any
    }
    loadDirectConnectionOptions: () => any
    loadDirectConnectionOptionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDirectConnectionOptionsSuccess: (
        directConnectionOptions: DirectConnectionSourceOptionApi[],
        payload?: any
    ) => {
        directConnectionOptions: DirectConnectionSourceOptionApi[]
        payload?: any
    }
    maybeLoadConnectionOptions: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface connectionSelectorLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        connectionSelectOptions: (
            connectionOptions: ExternalDataSourceConnectionOptionApi[] | null,
            connectionOptionsLoading: boolean,
            directConnectionOptions: DirectConnectionSourceOptionApi[] | null,
            directConnectionOptionsLoading: boolean,
            featureFlags: FeatureFlagsSet
        ) => ConnectionSelectOptionGroup[]
    }
}

export type connectionSelectorLogicType = MakeLogicType<
    connectionSelectorLogicValues,
    connectionSelectorLogicActions,
    Record<string, any>,
    connectionSelectorLogicMeta
>

export const connectionSelectorLogic = kea<connectionSelectorLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'connectionSelectorLogic']),
    connect(() => ({
        actions: [sourcesDataLogic, ['loadSourcesSuccess']],
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        maybeLoadConnectionOptions: true,
    }),
    loaders(() => ({
        connectionOptions: [
            null as ExternalDataSourceConnectionOptionApi[] | null,
            {
                loadConnectionOptions: async (): Promise<ExternalDataSourceConnectionOptionApi[]> => {
                    try {
                        // The projects route treats the path param as a team id (environments transition),
                        // so pass the current team id to keep per-environment scoping.
                        return await externalDataSourcesConnectionsList(String(ApiConfig.getCurrentTeamId()))
                    } catch (error: any) {
                        if (error?.status === 403) {
                            return []
                        }

                        return []
                    }
                },
            },
        ],
        directConnectionOptions: [
            null as DirectConnectionSourceOptionApi[] | null,
            {
                loadDirectConnectionOptions: async (): Promise<DirectConnectionSourceOptionApi[]> => {
                    try {
                        return await externalDataSourcesDirectConnectionOptionsList(
                            String(ApiConfig.getCurrentTeamId())
                        )
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),
    selectors({
        connectionSelectOptions: [
            (s) => [
                s.connectionOptions,
                s.connectionOptionsLoading,
                s.directConnectionOptions,
                s.directConnectionOptionsLoading,
                s.featureFlags,
            ],
            (
                connectionOptions: ExternalDataSourceConnectionOptionApi[] | null,
                connectionOptionsLoading: boolean,
                directConnectionOptions: DirectConnectionSourceOptionApi[] | null,
                directConnectionOptionsLoading: boolean,
                featureFlags: FeatureFlagsSet
            ): ConnectionSelectOptionGroup[] => {
                const sourceOptions = connectionOptionsLoading
                    ? [{ value: LOADING_CONNECTIONS, label: 'Loading...', disabled: true }]
                    : (connectionOptions ?? []).map((source) => {
                          const isManagedWarehouse = isManagedWarehouseConnection(source)
                          return {
                              value: source.id,
                              label: getConnectionOptionLabel(source),
                              iconSrc: isManagedWarehouse ? IconPostHog : ENGINE_ICONS[getConnectionEngine(source)],
                              hidden: isManagedWarehouse && !!featureFlags[FEATURE_FLAGS.MANAGED_TRINO_QUERY],
                              ...(isManagedWarehouse
                                  ? {}
                                  : { managementUrl: urls.dataWarehouseSource(`managed-${source.id}`) }),
                          }
                      })

                // Driven by the backend direct-SQL capability surface so the menu never drifts from
                // the engines we actually support (a new direct source shows up with no frontend change).
                const directConnectionSubmenu = directConnectionOptionsLoading
                    ? [{ value: LOADING_CONNECTIONS, label: 'Loading...', disabled: true }]
                    : (directConnectionOptions ?? []).map((option) => ({
                          value: `${ADD_DIRECT_CONNECTION_PREFIX}${option.source_type}`,
                          label: option.label,
                          iconSrc: option.icon_path ?? undefined,
                      }))

                return [
                    {
                        options: [
                            {
                                value: POSTHOG_WAREHOUSE,
                                label: 'PostHog (ClickHouse)',
                                iconSrc: IconPostHog,
                            },
                            ...sourceOptions,
                        ],
                    },
                    {
                        options: [
                            { value: CONFIGURE_SOURCES, label: 'Configure sources' },
                            {
                                label: 'Add direct connection',
                                options: directConnectionSubmenu,
                            },
                        ],
                    },
                ]
            },
        ],
    }),
    // No afterMount auto-load: sqlEditorLogic connects this logic, so it mounts with every
    // embedded SQL editor (notebooks, logs, endpoints). Only surfaces that render the
    // connection selector should pay for the fetch — they call maybeLoadConnectionOptions.
    listeners(({ actions, values }) => ({
        maybeLoadConnectionOptions: () => {
            if (values.connectionOptions === null && !values.connectionOptionsLoading) {
                actions.loadConnectionOptions()
            }
            if (values.directConnectionOptions === null && !values.directConnectionOptionsLoading) {
                actions.loadDirectConnectionOptions()
            }
        },
        loadSourcesSuccess: () => {
            // Refresh only where the options were fetched in the first place.
            if (values.connectionOptions !== null) {
                actions.loadConnectionOptions()
            }
        },
    })),
])
