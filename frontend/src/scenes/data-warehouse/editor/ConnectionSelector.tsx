import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'
import { urls } from 'scenes/urls'

import { ADD_POSTGRES_DIRECT_CONNECTION, CONFIGURE_SOURCES, POSTHOG_WAREHOUSE } from './directConnections'
import { sqlEditorLogic } from './sqlEditorLogic'

export function ConnectionSelector(): JSX.Element | null {
    const { dataWarehouseSources } = useValues(externalDataSourcesLogic)
    const { loadSources } = useActions(externalDataSourcesLogic)
    const { sourceQuery, isDirectQueryEnabled, isDuckgresEnabled, connectionSelectorOptions, selectedConnectionValue } =
        useValues(sqlEditorLogic)
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)

    useEffect(() => {
        if (isDirectQueryEnabled && !dataWarehouseSources) {
            loadSources()
        }
    }, [isDirectQueryEnabled, dataWarehouseSources, loadSources])
    // Strip the legacy top-level connectionId so source.connectionId stays canonical.
    const { connectionId: _legacyConnectionId, ...sourceQueryWithoutLegacyConnectionId } =
        sourceQuery as typeof sourceQuery & {
            connectionId?: string
        }

    if (!isDirectQueryEnabled && !isDuckgresEnabled) {
        return null
    }

    return (
        <LemonSelect
            size="small"
            fullWidth
            className="flex-1"
            value={selectedConnectionValue}
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
            options={connectionSelectorOptions}
        />
    )
}
