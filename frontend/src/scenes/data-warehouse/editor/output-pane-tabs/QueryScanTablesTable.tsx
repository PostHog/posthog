import { LemonTable } from '@posthog/lemon-ui'

import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import {
    ScanEstimate,
    ScanEstimatePrecision,
    ScanEstimateSource,
    TableScanEstimate,
} from '~/queries/schema/schema-general'

import { describeTableScan } from './queryScanSummary'

const SOURCE_LABELS: Record<ScanEstimateSource, string> = {
    [ScanEstimateSource.Events]: 'events',
    [ScanEstimateSource.Clickhouse]: 'PostHog',
    [ScanEstimateSource.Warehouse]: 'warehouse',
    [ScanEstimateSource.Direct]: 'external database',
    [ScanEstimateSource.Static]: 'built-in',
}

// `Measured` is not a success tag. It says the number has a model behind it and is checked against what
// the query actually read, not that the number is small.
const PRECISION_TAGS: Record<ScanEstimatePrecision, { type: LemonTagType; label: string }> = {
    [ScanEstimatePrecision.Measured]: { type: 'default', label: 'Estimated' },
    [ScanEstimatePrecision.SizeOnly]: { type: 'muted', label: 'Size only' },
    [ScanEstimatePrecision.Unknown]: { type: 'muted', label: 'Not estimated' },
}

interface QueryScanTablesTableProps {
    estimate: ScanEstimate
}

export function QueryScanTablesTable({ estimate }: QueryScanTablesTableProps): JSX.Element {
    return (
        <>
            <p className="text-xs px-2 pt-1 mb-1">
                What the query reads from each table. A table with no estimate is not counted in the total.
            </p>
            <LemonTable<TableScanEstimate>
                size="small"
                dataSource={estimate.tables}
                columns={[
                    {
                        key: 'table',
                        title: 'Table',
                        render: (_, { name }) => <code className="text-xs">{name}</code>,
                    },
                    {
                        key: 'source',
                        title: 'Source',
                        render: (_, { source }) => <span className="text-xs">{SOURCE_LABELS[source]}</span>,
                    },
                    {
                        key: 'reads',
                        title: 'Reads',
                        render: (_, table) => <span className="text-xs">{describeTableScan(table)}</span>,
                    },
                    {
                        key: 'precision',
                        title: 'Estimate',
                        render: (_, { precision }) => (
                            <LemonTag type={PRECISION_TAGS[precision].type}>{PRECISION_TAGS[precision].label}</LemonTag>
                        ),
                    },
                ]}
            />
        </>
    )
}
