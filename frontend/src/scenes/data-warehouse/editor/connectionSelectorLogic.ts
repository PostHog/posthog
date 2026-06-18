import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import type { ExternalDataSourceConnectionOption } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconDuckDB from 'public/services/duckdb.svg'
import IconMySQL from 'public/services/mysql.png'
import IconPostgres from 'public/services/postgres.png'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'

import type { connectionSelectorLogicType } from './connectionSelectorLogicType'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const ADD_MYSQL_DIRECT_CONNECTION = '__add_mysql_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

export interface ConnectionSelectOption {
    value: string
    label: string
    disabled?: boolean
    iconSrc?: string
    managementUrl?: string
}

export interface ConnectionSelectOptionGroup {
    options: ConnectionSelectOption[]
}

type ConnectionEngine = 'duckdb' | 'postgres' | 'mysql'

const ENGINE_LABELS: Record<ConnectionEngine, string> = {
    duckdb: 'DuckDB',
    postgres: 'Postgres',
    mysql: 'MySQL',
}

const ENGINE_ICONS: Record<ConnectionEngine, string> = {
    duckdb: IconDuckDB,
    postgres: IconPostgres,
    mysql: IconMySQL,
}

function getConnectionEngine(source: Pick<ExternalDataSourceConnectionOption, 'engine'>): ConnectionEngine {
    if (source.engine === 'duckdb' || source.engine === 'mysql') {
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
                            { value: ADD_POSTGRES_DIRECT_CONNECTION, label: '+ Add Postgres direct connection' },
                            { value: ADD_MYSQL_DIRECT_CONNECTION, label: '+ Add MySQL direct connection' },
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
