import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonTable, LemonTableColumn, LemonTag } from '@posthog/lemon-ui'

import { AppMetricsSparkline } from 'lib/components/AppMetrics/AppMetricsSparkline'

import { DATA_WAREHOUSE_APP_SOURCE } from 'products/data_warehouse/frontend/shared/components/metrics/DataWarehouseMetrics'
import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { DestinationIcon, destinationTypeLabel } from './DestinationIcon'
import { destinationTarget } from './destinationTarget'

export interface DestinationListProps {
    destinations: ExternalDataDestinationApi[]
    loading: boolean
    /** Destinations currently syncing. Rows not listed here render as off. */
    selectedIds: string[]
    onToggle: (destinationId: string) => void
    onEdit: (destination: ExternalDataDestinationApi) => void
    /** Set to make every toggle read-only, e.g. while a table inherits its source's set. */
    toggleDisabledReason?: string
    /**
     * The source these destinations belong to. Set it to show what each one has been receiving.
     * Left unset before the source exists, as in the creation wizard, where there is nothing yet.
     */
    metricsSourceId?: string
}

export function DestinationList({
    destinations,
    loading,
    selectedIds,
    onToggle,
    onEdit,
    toggleDisabledReason,
    metricsSourceId,
}: DestinationListProps): JSX.Element {
    const columns: LemonTableColumn<ExternalDataDestinationApi, any>[] = [
        {
            title: '',
            key: 'icon',
            width: 0,
            render: (_, destination) => <DestinationIcon type={destination.type} />,
        },
        {
            title: 'Name',
            key: 'name',
            sorter: (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base', numeric: true }),
            render: (_, destination) => (
                <div className="flex flex-col">
                    <span className="font-semibold">{destination.name}</span>
                    {destinationTarget(destination) ? (
                        <span className="text-muted text-xs">{destinationTarget(destination)}</span>
                    ) : null}
                </div>
            ),
        },
        {
            title: 'Type',
            key: 'type',
            render: (_, destination) => (
                <LemonTag type={destination.is_posthog_warehouse ? 'highlight' : 'default'}>
                    {destinationTypeLabel(destination.type)}
                </LemonTag>
            ),
        },
        ...(metricsSourceId
            ? [
                  {
                      title: 'Rows synced (7d)',
                      key: 'rows_synced_sparkline',
                      render: function RenderSparkline(_: unknown, destination: ExternalDataDestinationApi) {
                          return (
                              <AppMetricsSparkline
                                  logicKey={`dwh-destination-sparkline-${destination.id}`}
                                  loadOnChanges
                                  successMetricNames={['rows_synced']}
                                  metricLabels={{ rows_synced: 'Rows synced' }}
                                  forceParams={{
                                      appSource: DATA_WAREHOUSE_APP_SOURCE,
                                      appSourceId: metricsSourceId,
                                      // Runs record each destination on its own, without a schema,
                                      // so one series covers every table on the source.
                                      instanceId: destination.id,
                                      metricName: ['rows_synced'],
                                      breakdownBy: 'metric_name',
                                      interval: 'day',
                                      dateFrom: '-7d',
                                  }}
                              />
                          )
                      },
                  },
              ]
            : []),
        {
            title: '',
            key: 'actions',
            width: 0,
            render: (_, destination) => (
                <div className="flex gap-2 items-center justify-end">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        onClick={() => onEdit(destination)}
                        data-attr="warehouse-destination-edit"
                        tooltip={
                            destination.is_posthog_warehouse
                                ? 'The PostHog warehouse is managed for you'
                                : 'Edit this destination'
                        }
                        disabledReason={
                            destination.is_posthog_warehouse ? 'The PostHog warehouse is managed for you' : undefined
                        }
                    />
                    {/* Every toggle stays free, the last one on included, so a person can turn the
                        warehouse off before turning another destination on. The caller's save button
                        rejects an empty set. */}
                    <LemonSwitch
                        checked={selectedIds.includes(destination.id)}
                        onChange={() => onToggle(destination.id)}
                        data-attr="warehouse-destination-toggle"
                        disabledReason={toggleDisabledReason}
                    />
                </div>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={destinations}
            loading={loading}
            rowKey={(destination) => destination.id}
            columns={columns}
            emptyState="No destinations yet. Add one to sync these tables somewhere besides PostHog."
        />
    )
}
