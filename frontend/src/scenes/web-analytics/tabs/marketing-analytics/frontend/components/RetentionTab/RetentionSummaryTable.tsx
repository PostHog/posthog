import { IconInfo } from '@posthog/icons'
import { LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { gradateColor } from 'lib/utils/colors'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { MarketingAnalyticsRetentionRow } from '~/queries/schema/schema-general'

import { displayBreakdownValue } from '../../logic/marketingBreakdown'
import { SUMMARY_PERIODS, SummaryRow, summarizeByBreakdown } from './summarizeByBreakdown'

/** Same values as the per-cohort tables, so a rate reads as the same shade in both. */
const CELL_COLOR = '#1d4aff'
const CELL_COLOR_FLOOR = 0.1
const CELL_TEXT_LIGHT_THRESHOLD = 0.4

export function RetentionSummaryTable({
    rows,
    labels,
    dimensionLabel,
}: {
    rows: MarketingAnalyticsRetentionRow[]
    labels: string[]
    dimensionLabel: string
}): JSX.Element {
    const summary = summarizeByBreakdown(rows)

    const columns: LemonTableColumn<SummaryRow, any>[] = [
        {
            title: dimensionLabel,
            dataIndex: 'breakdownValue',
            render: (_, row) => (
                <span className="font-semibold">{displayBreakdownValue(row.breakdownValue, dimensionLabel)}</span>
            ),
        },
        {
            title: 'Acquired',
            tooltip: `How many people this ${dimensionLabel.toLowerCase()} acquired, added up across the cohorts shown in the tables below.`,
            dataIndex: 'acquired',
            align: 'right',
            sorter: (a, b) => a.acquired - b.acquired,
            render: (_, row) => humanFriendlyNumber(row.acquired),
        },
        ...labels.slice(0, SUMMARY_PERIODS).map((label, period) => ({
            title: label,
            tooltip:
                'The share of people who came back this many periods after arriving, pooled across cohorts and weighted by cohort size.',
            key: label,
            align: 'center' as const,
            // -1 puts a period no cohort has reached below every real rate, rather than level with 0%.
            defaultSortOrder: -1 as const,
            sorter: (a: SummaryRow, b: SummaryRow) => (a.cells[period].rate ?? -1) - (b.cells[period].rate ?? -1),
            render: (_: any, row: SummaryRow) => {
                const cell = row.cells[period]
                if (cell.rate === null) {
                    return (
                        <Tooltip title="No cohort has finished this period yet.">
                            <span className="text-muted">–</span>
                        </Tooltip>
                    )
                }
                return (
                    <Tooltip
                        title={`${humanFriendlyNumber(cell.returned)} of ${humanFriendlyNumber(cell.eligible)}, across ${cell.cohorts} ${cell.cohorts === 1 ? 'cohort' : 'cohorts'}`}
                    >
                        <div
                            className="rounded px-2 py-1"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                backgroundColor: gradateColor(CELL_COLOR, cell.rate, CELL_COLOR_FLOOR),
                                color: cell.rate > CELL_TEXT_LIGHT_THRESHOLD ? '#fff' : 'var(--text-3000)',
                            }}
                        >
                            {percentage(cell.rate, 1)}
                        </div>
                    </Tooltip>
                )
            },
        })),
    ]

    return (
        <div>
            <div className="text-muted mb-1 flex flex-wrap items-center gap-1 text-xs font-semibold uppercase">
                <span>Compare {dimensionLabel.toLowerCase()}s</span>
                <Tooltip
                    title={`Every cohort of a ${dimensionLabel.toLowerCase()} blended into one row. People and returns are summed and the rate is recalculated, so this is not an average of the percentages below. A cohort of five thousand counts for more than one of fifty. "Other" is left out here.`}
                >
                    <IconInfo className="text-base" />
                </Tooltip>
            </div>
            <LemonTable columns={columns} dataSource={summary} size="small" firstColumnSticky />
            <div className="text-secondary mt-1 text-xs">
                Each column only counts cohorts that finished that period, so later columns rest on fewer people.
                Compare within a column, not across.
            </div>
        </div>
    )
}
