import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'
import { urls } from 'scenes/urls'

import IconPostHog from 'public/posthog-icon.svg'
import IconPostgres from 'public/services/postgres.png'

import { sqlEditorLogic } from './sqlEditorLogic'

export const POSTHOG_WAREHOUSE = '__posthog_warehouse__'
export const LOADING_CONNECTIONS = '__loading_connections__'
export const ADD_POSTGRES_DIRECT_CONNECTION = '__add_postgres_direct_connection__'
export const CONFIGURE_SOURCES = '__configure_sources__'

const sourceIcon = (src: string): JSX.Element => (
    <img src={src} alt="" width={16} height={16} className="object-contain rounded" />
)

export function ConnectionSelector(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { dataWarehouseSources, dataWarehouseSourcesLoading } = useValues(externalDataSourcesLogic)
    const { loadSources } = useActions(externalDataSourcesLogic)
    const { sourceQuery, selectedConnectionId } = useValues(sqlEditorLogic)
    const { setSourceQuery, syncUrlWithQuery } = useActions(sqlEditorLogic)
    const isDirectQueryEnabled = !!featureFlags[FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]

    useEffect(() => {
        if (isDirectQueryEnabled && !dataWarehouseSources) {
            loadSources()
        }
    }, [isDirectQueryEnabled, dataWarehouseSources, loadSources])

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
                  icon: sourceIcon(IconPostgres),
              }))

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
    }, [dataWarehouseSourcesLoading, directPostgresSources])
    // Strip the legacy top-level connectionId so source.connectionId stays canonical.
    const { connectionId: _legacyConnectionId, ...sourceQueryWithoutLegacyConnectionId } =
        sourceQuery as typeof sourceQuery & {
            connectionId?: string
        }

    const selectedValue = dataWarehouseSourcesLoading
        ? LOADING_CONNECTIONS
        : selectedConnectionId && directPostgresSources.some((source) => source.id === selectedConnectionId)
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
