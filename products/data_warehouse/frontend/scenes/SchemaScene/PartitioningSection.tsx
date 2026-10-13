import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    PartitionGranularityEnumApi,
    PartitionModeEnumApi,
    SchemaPartitioningApi,
} from 'products/warehouse_sources/frontend/generated/api.schemas'

import { schemaPartitioningLogic } from './schemaPartitioningLogic'

export interface PartitioningSectionProps {
    schemaId: string
}

const GRANULARITY_OPTIONS: { value: PartitionGranularityEnumApi; label: string }[] = [
    { value: PartitionGranularityEnumApi.Hour, label: 'Hour' },
    { value: PartitionGranularityEnumApi.Day, label: 'Day' },
    { value: PartitionGranularityEnumApi.Week, label: 'Week' },
    { value: PartitionGranularityEnumApi.Month, label: 'Month' },
]

function currentPartitioningSummary(partitioning: SchemaPartitioningApi): string {
    const columns = partitioning.columns.join(', ')
    switch (partitioning.mode) {
        case PartitionModeEnumApi.Datetime:
            return `This table is partitioned by ${columns}, one partition per ${partitioning.date_granularity ?? 'date range'}. A query that filters on ${columns} reads only the matching partitions.`
        case PartitionModeEnumApi.Md5:
            return `This table is partitioned by a hash of ${columns}. A query that filters on a date reads the whole table.`
        case PartitionModeEnumApi.Numerical:
            return `This table is partitioned by ranges of ${columns}. A query that filters on a date reads the whole table.`
        default:
            return 'This table is not partitioned. Every query reads the whole table.'
    }
}

export function PartitioningSection({ schemaId }: PartitioningSectionProps): JSX.Element {
    const logic = schemaPartitioningLogic({ schemaId })
    const { partitioning, partitioningLoading, draftColumn, draftGranularity, saveDisabledReason } = useValues(logic)
    const { setDraftColumn, setDraftGranularity, save } = useActions(logic)

    if (!partitioning) {
        return partitioningLoading ? (
            <LemonSkeleton className="h-32" />
        ) : (
            <LemonBanner type="error">Couldn't load the partitioning of this table. Refresh the page.</LemonBanner>
        )
    }

    return (
        <div className="flex flex-col gap-4 max-w-160">
            <div>
                <h2 className="text-base font-semibold mb-1">Partitioning</h2>
                <p className="text-sm text-secondary">
                    Partition a large table by the date column your queries filter on, so they read less data and run
                    faster.
                </p>
            </div>

            <p className="m-0">{currentPartitioningSummary(partitioning)}</p>

            {partitioning.change_pending && (
                <LemonBanner type="info">A change to the partitioning is waiting for the next sync.</LemonBanner>
            )}

            {partitioning.available_columns.length === 0 ? (
                <LemonBanner type="info">
                    This table has no date column to partition by. If it has not synced yet, check again after its first
                    sync.
                </LemonBanner>
            ) : (
                <>
                    <LemonField.Pure
                        label="Date column"
                        help="Choose a column whose value never changes for a row, such as a creation time. If the value changes, an incremental sync can store the row twice."
                    >
                        <LemonSelect
                            value={draftColumn}
                            onChange={(column) => column && setDraftColumn(column)}
                            options={partitioning.available_columns.map((column) => ({ value: column, label: column }))}
                            placeholder="Choose a column"
                            data-attr="warehouse-schema-partitioning-column"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="One partition per"
                        help="Use a shorter period for a larger table. PostHog can change it later to keep partitions a size that syncs can handle."
                    >
                        <LemonSelect
                            value={draftGranularity}
                            onChange={(granularity) => granularity && setDraftGranularity(granularity)}
                            options={GRANULARITY_OPTIONS}
                            data-attr="warehouse-schema-partitioning-granularity"
                        />
                    </LemonField.Pure>
                    <div>
                        <LemonButton
                            type="primary"
                            onClick={save}
                            loading={partitioningLoading}
                            disabledReason={saveDisabledReason}
                            data-attr="warehouse-schema-partitioning-save"
                        >
                            Change partitioning
                        </LemonButton>
                    </div>
                </>
            )}
        </div>
    )
}
