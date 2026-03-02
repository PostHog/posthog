import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'

import { sqlEditorLogic } from './sqlEditorLogic'

const POSTHOG_WAREHOUSE = '__posthog_warehouse__'

export function ConnectionSelector(): JSX.Element {
    const { dataWarehouseSources } = useValues(externalDataSourcesLogic)
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

    const options = useMemo(
        () => [
            { value: POSTHOG_WAREHOUSE, label: 'PostHog Data Warehouse' },
            ...directPostgresSources.map((source) => ({
                value: source.id,
                label: source.prefix || source.source_id,
            })),
        ],
        [directPostgresSources]
    )

    const selectedValue =
        sourceQuery.source.connectionId && options.some((option) => option.value === sourceQuery.source.connectionId)
            ? sourceQuery.source.connectionId
            : POSTHOG_WAREHOUSE

    return (
        <LemonSelect<string>
            size="small"
            className="min-w-64"
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
