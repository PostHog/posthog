import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'
import { LineChart, TimeSeriesLineChart, useChartTheme } from '@posthog/quill-charts'

import { AccessDenied } from 'lib/components/AccessDenied'
import { userLogic } from 'scenes/userLogic'

import {
    mixModelLogic,
    type MmmCurveRow,
    type MmmDatasetResponse,
    type MmmRoiRow,
    type MmmSpendPanelRow,
} from '../../logic/mixModelLogic'

export function MixModelTab(): JSX.Element {
    const { user } = useValues(userLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="Mix model is a staff-only preview while in development." />
    }

    return <MixModelContent />
}

function MixModelContent(): JSX.Element {
    const {
        dataset,
        datasetLoading,
        datasetCsvUrl,
        runs,
        run,
        selectedJobId,
        decomposition,
        curves,
        roi,
        budgetRecommendation,
        runDetailLoading,
        runReadError,
    } = useValues(mixModelLogic)
    const { setSelectedJobId } = useActions(mixModelLogic)

    return (
        <div className="flex flex-col gap-4 mt-4">
            <LemonBanner type="info">
                Marketing mix modeling is a staff-only proof of concept. All recommendations are{' '}
                <strong>advisory only</strong> — nothing here is applied automatically.
            </LemonBanner>

            <DatasetSection dataset={dataset} loading={datasetLoading} csvUrl={datasetCsvUrl} />

            <div className="flex items-center gap-2">
                <span className="font-semibold">Model run</span>
                <LemonSelect
                    size="small"
                    value={selectedJobId}
                    onChange={(jobId) => setSelectedJobId(jobId)}
                    loading={runDetailLoading}
                    options={[
                        { value: null, label: 'Latest run' },
                        ...runs.map((r) => ({
                            value: r.job_id,
                            label: `${r.computed_at?.slice(0, 16).replace('T', ' ')} · R²=${r.r_squared?.toFixed(2)}`,
                        })),
                    ]}
                    placeholder="Latest run"
                />
            </div>

            {runReadError ? (
                <LemonBanner type="error">Couldn't load marketing mix model runs: {runReadError}</LemonBanner>
            ) : !run && !runDetailLoading ? (
                <LemonBanner type="info">
                    No marketing mix model has been computed for this project yet. Results appear here once a model run
                    completes.
                </LemonBanner>
            ) : (
                <>
                    {run && run.status !== 'ok' ? (
                        <LemonBanner type="warning">
                            This run is <strong>{run.status}</strong> — some results are placeholder or unreliable and
                            should not be acted on. Re-run the model once the issue is resolved.
                        </LemonBanner>
                    ) : null}
                    <RunDiagnostics run={run} />
                    <DecompositionSection decomposition={decomposition} loading={runDetailLoading} />
                    <ResponseCurvesSection curves={curves} loading={runDetailLoading} />
                    <RoiSection roi={roi} budgetRecommendation={budgetRecommendation} loading={runDetailLoading} />
                </>
            )}

            <CalibrationSection />
        </div>
    )
}

function DatasetSection({
    dataset,
    loading,
    csvUrl,
}: {
    dataset: MmmDatasetResponse | null
    loading: boolean
    csvUrl: string
}): JSX.Element {
    const columns: LemonTableColumns<MmmSpendPanelRow> = [
        { title: 'Week', dataIndex: 'week' },
        { title: 'Channel', dataIndex: 'channel' },
        { title: 'Spend', dataIndex: 'spend', render: (_, r) => r.spend.toLocaleString() },
        { title: 'Impressions', dataIndex: 'impressions', render: (_, r) => r.impressions.toLocaleString() },
        { title: 'Clicks', dataIndex: 'clicks', render: (_, r) => r.clicks.toLocaleString() },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
                <h3 className="m-0">Modeling dataset</h3>
                <LemonButton type="secondary" size="small" to={csvUrl} targetBlank disableClientSideRouting>
                    Download CSV
                </LemonButton>
            </div>
            {dataset && dataset.status !== 'ok' ? (
                <LemonBanner type="warning">{dataset.message}</LemonBanner>
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={dataset?.spend_panel ?? []}
                loading={loading}
                size="small"
                rowKey={(r) => `${r.week}-${r.channel}`}
                emptyState="No spend data in the modeling window."
            />
        </div>
    )
}

function RunDiagnostics({ run }: { run: { r_squared: number; mape: number; divergences: number } | null }): JSX.Element | null {
    if (!run) {
        return null
    }
    return (
        <div className="flex gap-2">
            <LemonTag type="muted">R² {run.r_squared?.toFixed(3)}</LemonTag>
            <LemonTag type="muted">MAPE {run.mape?.toFixed(3)}</LemonTag>
            <LemonTag type={run.divergences > 0 ? 'warning' : 'muted'}>Divergences {run.divergences}</LemonTag>
        </div>
    )
}

function DecompositionSection({
    decomposition,
    loading,
}: {
    decomposition: { labels: string[]; series: { key: string; label: string; data: number[] }[] }
    loading: boolean
}): JSX.Element {
    const theme = useChartTheme()
    // The long→wide transform lives in the logic's `decomposition` selector. Render as lines (not
    // filled/stacked areas): the baseline contribution can be negative when the model over-attributes a
    // week, and an auto-stacked area chart misrepresents mixed-sign series.

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">Contribution decomposition</h3>
            {loading || decomposition.labels.length === 0 ? (
                <LemonBanner type="info">No contribution data for this run.</LemonBanner>
            ) : (
                <div className="h-80">
                    <TimeSeriesLineChart
                        series={decomposition.series}
                        labels={decomposition.labels}
                        theme={theme}
                        config={{ xAxis: { interval: 'week' }, legend: { show: true } }}
                    />
                </div>
            )}
        </div>
    )
}

function ResponseCurvesSection({ curves, loading }: { curves: MmmCurveRow[]; loading: boolean }): JSX.Element {
    const theme = useChartTheme()
    const channels = Array.from(new Set(curves.map((c) => c.channel)))

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">Response curves</h3>
            {loading || channels.length === 0 ? (
                <LemonBanner type="info">No response curves for this run.</LemonBanner>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {channels.map((channel) => {
                        const points = curves
                            .filter((c) => c.channel === channel)
                            .sort((a, b) => a.spend_point - b.spend_point)
                        return (
                            <div key={channel} className="flex flex-col gap-1">
                                <span className="font-semibold">{channel}</span>
                                <div className="h-48">
                                    <LineChart
                                        labels={points.map((p) => p.spend_point.toFixed(0))}
                                        series={[
                                            {
                                                key: channel,
                                                label: 'Incremental outcome',
                                                data: points.map((p) => p.incremental_outcome),
                                                fill: { lowerData: points.map((p) => p.incremental_lower) },
                                            },
                                        ]}
                                        theme={theme}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

function RoiSection({
    roi,
    budgetRecommendation,
    loading,
}: {
    roi: MmmRoiRow[]
    budgetRecommendation: { totalShift: number; increases: MmmRoiRow[]; decreases: MmmRoiRow[] }
    loading: boolean
}): JSX.Element {
    const columns: LemonTableColumns<MmmRoiRow> = [
        {
            title: 'Channel',
            dataIndex: 'channel',
            render: (_, r) => (
                <span className="flex items-center gap-1">
                    {r.channel}
                    {r.calibrated ? <LemonTag type="success">calibrated</LemonTag> : null}
                </span>
            ),
        },
        { title: 'ROI', dataIndex: 'roi', render: (_, r) => r.roi.toFixed(2) },
        { title: 'Marginal ROI', dataIndex: 'marginal_roi', render: (_, r) => r.marginal_roi.toFixed(2) },
        { title: 'Current spend', dataIndex: 'current_spend', render: (_, r) => r.current_spend.toLocaleString() },
        {
            title: 'Recommended spend',
            dataIndex: 'recommended_spend',
            render: (_, r) => r.recommended_spend.toLocaleString(),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">ROI & budget recommendation</h3>
            {budgetRecommendation.totalShift > 0 ? (
                <LemonBanner type="info">
                    Advisory: shift ~{budgetRecommendation.totalShift.toLocaleString()} of weekly spend from{' '}
                    {budgetRecommendation.decreases.map((r) => r.channel).join(', ') || '—'} towards{' '}
                    {budgetRecommendation.increases.map((r) => r.channel).join(', ') || '—'} to equalize marginal ROI.
                </LemonBanner>
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={roi}
                loading={loading}
                size="small"
                rowKey={(r) => r.channel}
                emptyState="No ROI estimates for this run."
            />
        </div>
    )
}

function CalibrationSection(): JSX.Element {
    const { calibrations, calibrationsResponseLoading, calibrationDraft, isCalibrationDraftValid } =
        useValues(mixModelLogic)
    const { setCalibrationDraft, submitCalibrationDraft } = useActions(mixModelLogic)

    const columns: LemonTableColumns<(typeof calibrations)[number]> = [
        { title: 'Channel', dataIndex: 'channel' },
        { title: 'Lift %', dataIndex: 'lift_pct' },
        { title: 'CI low', dataIndex: 'ci_low' },
        { title: 'CI high', dataIndex: 'ci_high' },
        { title: 'Source', dataIndex: 'source' },
    ]

    return (
        <div className="flex flex-col gap-2">
            <h3 className="m-0">Lift calibrations</h3>
            <p className="text-muted m-0">
                Calibrate a channel with a measured lift to tighten its prior in the next model run.
            </p>
            <LemonTable
                columns={columns}
                dataSource={calibrations}
                loading={calibrationsResponseLoading}
                size="small"
                rowKey={(r) => r.channel}
                emptyState="No calibrations yet."
            />
            <div className="flex flex-wrap items-end gap-2">
                <LemonInput
                    placeholder="Channel"
                    value={calibrationDraft.channel}
                    onChange={(channel) => setCalibrationDraft({ channel })}
                />
                <LemonInput
                    type="number"
                    placeholder="Lift %"
                    value={calibrationDraft.lift_pct ?? undefined}
                    onChange={(lift_pct) => setCalibrationDraft({ lift_pct: lift_pct ?? null })}
                />
                <LemonInput
                    type="number"
                    placeholder="CI low"
                    value={calibrationDraft.ci_low ?? undefined}
                    onChange={(ci_low) => setCalibrationDraft({ ci_low: ci_low ?? null })}
                />
                <LemonInput
                    type="number"
                    placeholder="CI high"
                    value={calibrationDraft.ci_high ?? undefined}
                    onChange={(ci_high) => setCalibrationDraft({ ci_high: ci_high ?? null })}
                />
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => submitCalibrationDraft()}
                    loading={calibrationsResponseLoading}
                    disabledReason={isCalibrationDraftValid ? undefined : 'Fill all fields; CI low must be ≤ CI high'}
                >
                    Save calibration
                </LemonButton>
            </div>
        </div>
    )
}
