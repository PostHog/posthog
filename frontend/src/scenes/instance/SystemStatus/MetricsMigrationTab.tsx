import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconRefresh } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { MetricsMigrationDashboard, MetricsMigrationUncoveredMetric } from '~/types'

import { metricsMigrationLogic } from './metricsMigrationLogic'

function CoverageTag({ pct }: { pct: number }): JSX.Element {
    const type = pct >= 100 ? 'success' : pct >= 50 ? 'warning' : 'danger'
    return <LemonTag type={type}>{pct.toFixed(1)}%</LemonTag>
}

export function MetricsMigrationTab(): JSX.Element {
    const { report, reportLoading, live } = useValues(metricsMigrationLogic)
    const { loadReport, setLive } = useActions(metricsMigrationLogic)

    useEffect(() => {
        loadReport()
    }, [live, loadReport])

    if (reportLoading && !report) {
        return <div className="text-secondary">Loading…</div>
    }

    if (!report) {
        return (
            <div className="text-secondary">
                No Grafana coverage snapshot is deployed on this instance. Generate one from the{' '}
                <Link to="https://github.com/PostHog/grafana-dashboards/tree/master/coverage" target="_blank">
                    grafana-dashboards coverage report
                </Link>{' '}
                and redeploy.
            </div>
        )
    }

    const { summary } = report

    const dashboardColumns: LemonTableColumns<MetricsMigrationDashboard> = [
        {
            title: 'Dashboard',
            dataIndex: 'title',
            render: (_, dashboard) => (
                <Link
                    to={`https://github.com/PostHog/grafana-dashboards/blob/master/${dashboard.file}`}
                    target="_blank"
                >
                    {dashboard.title}
                </Link>
            ),
        },
        {
            title: 'Coverage',
            dataIndex: 'coverage_pct',
            render: (_, dashboard) => <CoverageTag pct={dashboard.coverage_pct} />,
            sorter: (a, b) => a.coverage_pct - b.coverage_pct,
        },
        {
            title: 'Metrics covered',
            dataIndex: 'covered_metrics',
            render: (_, dashboard) => `${dashboard.covered_metrics} / ${dashboard.metric_count}`,
            sorter: (a, b) => a.covered_metrics / a.metric_count - b.covered_metrics / b.metric_count,
        },
        {
            title: 'Status',
            dataIndex: 'status',
            render: (_, dashboard) => <LemonTag>{dashboard.status}</LemonTag>,
        },
    ]

    const uncoveredColumns: LemonTableColumns<MetricsMigrationUncoveredMetric> = [
        { title: 'Metric', dataIndex: 'name' },
        {
            title: 'Referenced by',
            dataIndex: 'dashboards',
            render: (_, metric) => metric.dashboards.join(', '),
        },
    ]

    return (
        <div className="deprecated-space-y-4">
            <div className="flex items-center gap-4">
                <h3 className="mb-0">Grafana → PostHog metrics migration</h3>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconRefresh />}
                    onClick={() => loadReport()}
                    loading={reportLoading}
                >
                    Refresh
                </LemonButton>
                <LemonCheckbox
                    checked={live}
                    onChange={setLive}
                    label="Recompute against live ingested names (this project, 7d)"
                />
            </div>

            <p className="text-secondary">
                Share of Grafana dashboard metric names that already flow into PostHog's own metrics product.
                {report.live ? ' Live counts against this project’s metric store.' : ' From the committed snapshot.'}
                {report.generated_at ? ` Snapshot generated ${report.generated_at}.` : ''}
            </p>

            <div className="flex gap-6">
                <div>
                    <div className="text-4xl font-bold">{summary.coverage_pct.toFixed(1)}%</div>
                    <div className="text-secondary">
                        {humanFriendlyNumber(summary.covered)} / {humanFriendlyNumber(summary.grafana_metric_names)}{' '}
                        metric names
                    </div>
                </div>
                <div>
                    <div className="text-4xl font-bold">{summary.dashboards_fully_covered}</div>
                    <div className="text-secondary">of {summary.dashboards_total} dashboards fully covered</div>
                </div>
                <div>
                    <div className="text-4xl font-bold">{humanFriendlyNumber(summary.posthog_ingested_names)}</div>
                    <div className="text-secondary">metric names ingested into PostHog</div>
                </div>
            </div>

            <LemonCollapse
                className="bg-surface-primary"
                multiple
                defaultActiveKeys={['dashboards']}
                panels={[
                    {
                        key: 'dashboards',
                        header: `Dashboards by coverage (${report.dashboards.length})`,
                        content: (
                            <LemonTable
                                dataSource={report.dashboards}
                                columns={dashboardColumns}
                                loading={reportLoading}
                                defaultSorting={{ columnKey: 'coverage_pct', order: -1 }}
                            />
                        ),
                    },
                    {
                        key: 'uncovered',
                        header: `Uncovered metric names (${report.uncovered.length})`,
                        content: (
                            <LemonTable
                                dataSource={report.uncovered}
                                columns={uncoveredColumns}
                                loading={reportLoading}
                            />
                        ),
                    },
                ]}
            />
        </div>
    )
}
