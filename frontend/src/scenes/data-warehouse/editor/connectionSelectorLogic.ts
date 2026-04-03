import { afterMount, connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { ExternalDataSourceConnectionOption } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconDuckDB from 'public/services/duckdb.svg'
import IconPostgres from 'public/services/postgres.png'

import type { connectionSelectorLogicType } from './connectionSelectorLogicType'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

export interface ConnectionSelectorLogicProps {
    selectedConnectionId?: string
}

export interface ConnectionSelectOption {
    value: string
    label: string
    disabled?: boolean
    iconSrc?: string
}

export interface ConnectionSelectOptionGroup {
    options: ConnectionSelectOption[]
}

function getConnectionEngine(source: Pick<ExternalDataSourceConnectionOption, 'engine'>): 'duckdb' | 'postgres' {
    return source.engine === 'duckdb' ? 'duckdb' : 'postgres'
}

export const connectionSelectorLogic = kea<connectionSelectorLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'connectionSelectorLogic']),
    props({ selectedConnectionId: undefined } as ConnectionSelectorLogicProps),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
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
        isDirectQueryEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY],
        ],
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
                              label: `${source.prefix ? source.prefix : source.id} (${engine === 'duckdb' ? 'DuckDB' : 'Postgres'})`,
                              iconSrc: engine === 'duckdb' ? IconDuckDB : IconPostgres,
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
                            { value: ADD_POSTGRES_DIRECT_CONNECTION, label: '+ Add postgres direct connection' },
                        ],
                    },
                ]
            },
        ],
        connectionSelectorValue: [
            (s) => [s.connectionOptions, s.connectionOptionsLoading, (_, props) => props.selectedConnectionId],
            (
                connectionOptions: ExternalDataSourceConnectionOption[] | null,
                connectionOptionsLoading: boolean,
                selectedConnectionId: string | undefined
            ): string => {
                if (connectionOptionsLoading) {
                    return LOADING_CONNECTIONS
                }

                if (
                    selectedConnectionId &&
                    (connectionOptions ?? []).some((source) => source.id === selectedConnectionId)
                ) {
                    return selectedConnectionId
                }

                return POSTHOG_WAREHOUSE
            },
        ],
    }),
    afterMount(({ actions, values }) => {
        if (values.isDirectQueryEnabled && values.connectionOptions === null && !values.connectionOptionsLoading) {
            actions.loadConnectionOptions()
        }
    }),
])
