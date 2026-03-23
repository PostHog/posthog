import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo, useState } from 'react'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { ExternalDataSourceConnectionOption } from '~/types'

import IconPostHog from 'public/posthog-icon.svg'
import IconDuckDB from 'public/services/duckdb.svg'
import IconPostgres from 'public/services/postgres.png'

import { sqlEditorLogic } from './sqlEditorLogic'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

const sourceIcon = (src: string): JSX.Element => (
    <img src={src} alt="" width={16} height={16} className="object-contain rounded" />
)

function getConnectionEngine(source: Pick<ExternalDataSourceConnectionOption, 'engine'>): 'duckdb' | 'postgres' {
    return source.engine === 'duckdb' ? 'duckdb' : 'postgres'
}

export function ConnectionSelector(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { sourceQuery, selectedConnectionId } = useValues(sqlEditorLogic)
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)
    const isDirectQueryEnabled = !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]
    const [connectionOptions, setConnectionOptions] = useState<ExternalDataSourceConnectionOption[] | null>(null)
    const [connectionOptionsLoading, setConnectionOptionsLoading] = useState(false)

    useEffect(() => {
        if (!isDirectQueryEnabled || connectionOptions !== null) {
            return
        }

        const abortController = new AbortController()
        setConnectionOptionsLoading(true)

        api.externalDataSources
            .connections({ signal: abortController.signal })
            .then((results) => {
                setConnectionOptions(results)
            })
            .catch((error: any) => {
                if (error?.status === 403) {
                    setConnectionOptions([])
                    return
                }

                if (error?.name !== 'AbortError') {
                    setConnectionOptions([])
                }
            })
            .finally(() => {
                if (!abortController.signal.aborted) {
                    setConnectionOptionsLoading(false)
                }
            })

        return () => {
            abortController.abort()
        }
    }, [isDirectQueryEnabled, connectionOptions])

    const options = useMemo(() => {
        const sourceOptions = connectionOptionsLoading
            ? [{ value: LOADING_CONNECTIONS, label: 'Loading...', disabled: true }]
            : (connectionOptions ?? []).map((source) => {
                  const engine = getConnectionEngine(source)

                  return {
                      value: source.id,
                      label: `${source.prefix ? source.prefix : source.id} (${engine === 'duckdb' ? 'DuckDB' : 'Postgres'})`,
                      icon: sourceIcon(engine === 'duckdb' ? IconDuckDB : IconPostgres),
                  }
              })

        return [
            {
                options: [
                    { value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)', icon: sourceIcon(IconPostHog) },
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
    }, [connectionOptions, connectionOptionsLoading])
    // Strip the legacy top-level connectionId so source.connectionId stays canonical.
    const { connectionId: _legacyConnectionId, ...sourceQueryWithoutLegacyConnectionId } =
        sourceQuery as typeof sourceQuery & {
            connectionId?: string
        }

    const selectedValue = connectionOptionsLoading
        ? LOADING_CONNECTIONS
        : selectedConnectionId && (connectionOptions ?? []).some((source) => source.id === selectedConnectionId)
          ? selectedConnectionId
          : POSTHOG_WAREHOUSE

    if (!isDirectQueryEnabled) {
        return null
    }

    return (
        <LemonSelect
            size="small"
            fullWidth
            className="flex-1"
            value={selectedValue}
            onChange={(nextValue) => {
                if (!nextValue || nextValue === POSTHOG_WAREHOUSE) {
                    setSourceQuery({
                        ...sourceQueryWithoutLegacyConnectionId,
                        source: {
                            ...sourceQuery.source,
                            connectionId: undefined,
                        },
                    } as typeof sourceQuery)
                    syncUrlWithQuery()
                    return
                }

                if (nextValue === ADD_POSTGRES_DIRECT_CONNECTION) {
                    router.actions.push(urls.dataWarehouseSourceNew('Postgres'))
                    return
                }

                if (nextValue === CONFIGURE_SOURCES) {
                    router.actions.push(urls.sources())
                    return
                }

                setSourceQuery({
                    ...sourceQueryWithoutLegacyConnectionId,
                    source: {
                        ...sourceQuery.source,
                        connectionId: nextValue,
                    },
                } as typeof sourceQuery)
                syncUrlWithQuery()
            }}
            options={options}
        />
    )
}
