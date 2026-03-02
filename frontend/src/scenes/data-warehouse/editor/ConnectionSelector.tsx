import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'
import { urls } from 'scenes/urls'

import { sqlEditorLogic } from './sqlEditorLogic'

const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
const LOADING_CONNECTIONS = '__loading_connections__'
const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'

export function ConnectionSelector(): JSX.Element {
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(externalDataSourcesLogic)
    const { loadSources } = useActions(externalDataSourcesLogic)
    const { sourceQuery } = useValues(sqlEditorLogic)
    const { setSourceQuery } = useActions(sqlEditorLogic)
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
                  value: source.connection_id,
                  label: source.prefix || source.source_id,
              }))

        return [
            { value: POSTHOG_WAREHOUSE, label: 'PostHog Data Warehouse' },
            ...sourceOptions,
            { value: ADD_POSTGRES_DIRECT_CONNECTION, label: '+ Add postgres direct connection' },
        ]
    }, [dataWarehouseSourcesLoading, directPostgresSources])

    const selectedValue =
        sourceQuery.source.connectionId && options.some((option) => option.value === sourceQuery.source.connectionId)
            ? sourceQuery.source.connectionId
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
                        ...sourceQuery,
                        source: {
                            ...sourceQuery.source,
                            connectionId: undefined,
                        },
                    })
                    setConnection(null, null)
                    loadDatabase()
                    return
                }

                if (nextValue === ADD_POSTGRES_DIRECT_CONNECTION) {
                    router.actions.push(urls.dataWarehouseSourceNew())
                    return
                }

                const selectedConnectionId = nextValue
                const selectedSource = directPostgresSources.find(
                    (source) => source.connection_id === selectedConnectionId
                )

                setSourceQuery({
                    ...sourceQuery,
                    source: {
                        ...sourceQuery.source,
                        connectionId: selectedConnectionId ?? undefined,
                    },
                })
                setConnection(selectedConnectionId, selectedSource?.source_id ?? null)
                loadDatabase()
            }}
            options={options}
        />
    )
}
