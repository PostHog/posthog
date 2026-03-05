import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'
import { urls } from 'scenes/urls'

import { sqlEditorLogic } from './sqlEditorLogic'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

export function ConnectionSelector(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(externalDataSourcesLogic)
    const { loadSources } = useActions(externalDataSourcesLogic)
    const { sourceQuery, selectedConnectionId } = useValues(sqlEditorLogic)
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)
    const { setConnection, loadDatabase } = useActions(databaseTableListLogic)

    useEffect(() => {
        if (!dataWarehouseSources) {
            loadSources()
        }
    }, [dataWarehouseSources, loadSources])

    const directPostgresSources = useMemo(
        () =>
            (dataWarehouseSources?.results ?? []).filter(
                (source) => source.access_method === 'direct' && source.source_type.toLowerCase().includes('postgres')
            ),
        [dataWarehouseSources]
    )

    const options = useMemo(() => {
        const sourceOptions = dataWarehouseSourcesLoading
            ? [{ value: LOADING_CONNECTIONS, label: 'Loading...', disabled: true }]
            : directPostgresSources.map((source) => ({
                  value: source.id,
                  label: `${source.prefix ? source.prefix : source.id} (Postgres)`,
              }))

        return [
            {
                options: [{ value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' }, ...sourceOptions],
            },
            {
                options: [
                    { value: CONFIGURE_SOURCES, label: 'Configure sources' },
                    { value: ADD_POSTGRES_DIRECT_CONNECTION, label: '+ Add postgres direct connection' },
                ],
            },
        ]
    }, [dataWarehouseSourcesLoading, directPostgresSources])

    const sourceQueryWithConnection = sourceQuery as typeof sourceQuery & { connectionId?: string }
    const selectedValue = dataWarehouseSourcesLoading
        ? LOADING_CONNECTIONS
        : selectedConnectionId && directPostgresSources.some((source) => source.id === selectedConnectionId)
          ? selectedConnectionId
          : POSTHOG_WAREHOUSE

    return (
        <LemonSelect
            size="small"
            fullWidth
            className="flex-1"
            value={selectedValue}
            onChange={(nextValue) => {
                if (!nextValue || nextValue === POSTHOG_WAREHOUSE) {
                    setSourceQuery({
                        ...sourceQueryWithConnection,
                        connectionId: undefined,
                        source: {
                            ...sourceQuery.source,
                            connectionId: undefined,
                        },
                    } as typeof sourceQuery)
                    setConnection(null)
                    loadDatabase()
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
                    ...sourceQueryWithConnection,
                    connectionId: nextValue,
                    source: {
                        ...sourceQuery.source,
                        connectionId: nextValue,
                    },
                } as typeof sourceQuery)
                setConnection(nextValue)
                loadDatabase()
                syncUrlWithQuery()
            }}
            options={options}
        />
    )
}
