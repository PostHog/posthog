import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { ExternalDataSourceConnectionOption } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconDuckDB from 'public/services/duckdb.svg'
import IconMySQL from 'public/services/mysql.png'
import IconPostgres from 'public/services/postgres.png'
import IconRedshift from 'public/services/redshift.png'
import IconSnowflake from 'public/services/snowflake.png'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import type { connectionSelectorLogicType } from './connectionSelectorLogicType'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const ADD_MYSQL_DIRECT_CONNECTION = '__add_mysql_direct_connection__'
export const ADD_SNOWFLAKE_DIRECT_CONNECTION = '__add_snowflake_direct_connection__'
export const ADD_REDSHIFT_DIRECT_CONNECTION = '__add_redshift_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

export interface ConnectionSelectOption {
    // A leaf carries a `value`; a node carries nested `options` and renders as a submenu.
    value?: string
    label: string
    disabled?: boolean
    iconSrc?: string
    managementUrl?: string
    options?: ConnectionSelectOption[]
}

export interface ConnectionSelectOptionGroup {
    options: ConnectionSelectOption[]
}

type ConnectionEngine = 'duckdb' | 'postgres' | 'mysql' | 'snowflake' | 'redshift'

const ENGINE_LABELS: Record<ConnectionEngine, string> = {
    duckdb: 'DuckDB',
    postgres: 'Postgres',
    mysql: 'MySQL',
    snowflake: 'Snowflake',
    redshift: 'Redshift',
}

const ENGINE_ICONS: Record<ConnectionEngine, string> = {
    duckdb: IconDuckDB,
    postgres: IconPostgres,
    mysql: IconMySQL,
    snowflake: IconSnowflake,
    redshift: IconRedshift,
}

function getConnectionEngine(source: Pick<ExternalDataSourceConnectionOption, 'engine'>): ConnectionEngine {
    if (
        source.engine === 'duckdb' ||
        source.engine === 'mysql' ||
        source.engine === 'snowflake' ||
        source.engine === 'redshift'
    ) {
        return source.engine
    }
    return 'postgres'
}

export function getConnectionSelectorValue(
    connectionOptions: ExternalDataSourceConnectionOption[] | null,
    connectionOptionsLoading: boolean,
    selectedConnectionId: string | undefined
): string {
    if (connectionOptionsLoading) {
        return LOADING_CONNECTIONS
    }

    if (selectedConnectionId && (connectionOptions ?? []).some((source) => source.id === selectedConnectionId)) {
        return selectedConnectionId
    }

    return POSTHOG_WAREHOUSE
}

export const connectionSelectorLogic = kea<connectionSelectorLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'connectionSelectorLogic']),
    connect(() => ({
        actions: [sourcesDataLogic, ['loadSourcesSuccess']],
    })),
    loaders(() => ({
        connectionOptions: [
            null as ExternalDataSourceConnectionOption[] | null,
            {
                loadConnectionOptions: async (): Promise<ExternalDataSourceConnectionOption[]> => {
                    try {
                        return await api.externalDataSources.connections()
                    } catch (error: any) {
                        if (error?.status === 403) {
                            return []
                        }

                        return []
                    }
                },
            },
        ],
    })),
    selectors({
        connectionSelectOptions: [
            (s) => [s.connectionOptions, s.connectionOptionsLoading],
            (
                connectionOptions: ExternalDataSourceConnectionOption[] | null,
                connectionOptionsLoading: boolean
            ): ConnectionSelectOptionGroup[] => {
                const sourceOptions = connectionOptionsLoading
                    ? [{ value: LOADING_CONNECTIONS, label: 'Loading...', disabled: true }]
                    : (connectionOptions ?? []).map((source) => {
                          const engine = getConnectionEngine(source)

                          return {
                              value: source.id,
                              label: `${source.prefix ? source.prefix : source.id} (${ENGINE_LABELS[engine]})`,
                              iconSrc: ENGINE_ICONS[engine],
                              managementUrl: urls.dataWarehouseSource(`managed-${source.id}`),
                          }
                      })

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
                                options: [
                                    {
                                        value: ADD_POSTGRES_DIRECT_CONNECTION,
                                        label: 'Postgres',
                                        iconSrc: IconPostgres,
                                    },
                                    { value: ADD_MYSQL_DIRECT_CONNECTION, label: 'MySQL', iconSrc: IconMySQL },
                                    {
                                        value: ADD_SNOWFLAKE_DIRECT_CONNECTION,
                                        label: 'Snowflake',
                                        iconSrc: IconSnowflake,
                                    },
                                    {
                                        value: ADD_REDSHIFT_DIRECT_CONNECTION,
                                        label: 'Redshift',
                                        iconSrc: IconRedshift,
                                    },
                                ],
                            },
                        ],
                    },
                ]
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.connectionOptions === null && !values.connectionOptionsLoading) {
            actions.loadConnectionOptions()
        }
    }),
    listeners(({ actions }) => ({
        loadSourcesSuccess: () => {
            actions.loadConnectionOptions()
        },
    })),
])
