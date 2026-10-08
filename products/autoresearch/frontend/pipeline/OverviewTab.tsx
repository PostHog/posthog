import { useValues } from 'kea'

import { LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchModelRoleEnumApi, AutoresearchPipelineApi } from '../generated/api.schemas'
import { PipelineStatusTag } from '../PipelineStatusTag'
import { FeatureImportanceChart } from './FeatureImportanceChart'

export function OverviewTab(): JSX.Element {
    const { pipeline, models } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }
    const champion = models.find((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    return (
        <div className="space-y-4">
            <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-muted">Status</span>
                <PipelineStatusTag status={pipeline.status} />
            </div>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <MetricCard label="Target event" value={pipeline.target_event} />
                <MetricCard label="Prediction horizon" value={`${pipeline.horizon_days ?? '—'}d`} />
                <MetricCard label="Training lookback" value={`${pipeline.training_lookback_days ?? '—'}d`} />
                <MetricCard
                    label="Budget remaining"
                    value={`${pipeline.iteration_budget_remaining} / ${pipeline.iteration_budget ?? '—'}`}
                />
            </div>
            {champion && (
                <div className="border rounded p-4 space-y-4">
                    <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-muted">Champion model</span>
                        {champion.is_preliminary && (
                            <Tooltip title="Promoted on holdout AUC alone. Realized metrics confirm it once prediction horizons elapse.">
                                <LemonTag type="warning">Preliminary</LemonTag>
                            </Tooltip>
                        )}
                    </div>
                    <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                        <MetricCard
                            label="Holdout AUC"
                            value={champion.holdout_score?.toFixed(3) ?? '—'}
                            tooltip="Offline AUC of the champion model, measured on held-out training data. Higher is better."
                        />
                        <MetricCard
                            label="Realized AUC"
                            value={champion.realized_score?.toFixed(3) ?? '—'}
                            tooltip="AUC of the champion model measured against actual outcomes once predictions matured. Higher is better."
                        />
                        <MetricCard
                            label="Calibration error"
                            value={champion.calibration_error?.toFixed(3) ?? '—'}
                            tooltip="Expected calibration error (ECE): how far predicted probabilities drift from observed rates. Lower is better."
                        />
                    </div>
                    <FeatureImportanceChart explanation={champion.model_explanation} />
                    {champion.agent_description && (
                        <div className="text-sm text-muted italic">"{champion.agent_description}"</div>
                    )}
                </div>
            )}
            <div className="border rounded p-4">
                <DetailRow label="Output person property">
                    <code>{pipeline.output_person_property ?? '—'}</code>
                </DetailRow>
                <DetailRow label="Training population">
                    <span className="font-mono text-xs">{populationSummary(pipeline.training_population)}</span>
                </DetailRow>
                <DetailRow label="Inference population">
                    <span className="font-mono text-xs">{populationSummary(pipeline.inference_population)}</span>
                </DetailRow>
                <DetailRow label="Last scored">
                    {pipeline.last_scored_at ? dayjs(pipeline.last_scored_at).fromNow() : 'Never'}
                </DetailRow>
                <DetailRow label="Created">
                    {dayjs(pipeline.created_at).format('MMM D, YYYY')}
                    {pipeline.created_by?.first_name ? ` by ${pipeline.created_by.first_name}` : ''}
                </DetailRow>
            </div>
            <p className="text-sm text-muted">
                Editing the target, populations, and budget in the UI is coming soon. For now, use the{' '}
                <code>autoresearch</code> API or MCP tools, or recreate the model.
            </p>
        </div>
    )
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex justify-between items-start gap-4 py-2 border-b last:border-0">
            <div className="text-sm font-semibold text-muted">{label}</div>
            <div className="text-sm text-right">{children}</div>
        </div>
    )
}

function populationSummary(population: AutoresearchPipelineApi['training_population']): string {
    if (!population || typeof population !== 'object' || Object.keys(population).length === 0) {
        return 'All users'
    }
    return JSON.stringify(population)
}

function MetricCard({ label, value, tooltip }: { label: string; value: string; tooltip?: string }): JSX.Element {
    const labelElement = (
        <div className={`text-xs font-semibold text-muted uppercase tracking-wide${tooltip ? ' cursor-help' : ''}`}>
            {label}
        </div>
    )
    return (
        <div className="border rounded p-3 space-y-1">
            {tooltip ? <Tooltip title={tooltip}>{labelElement}</Tooltip> : labelElement}
            <div className="text-lg font-bold truncate">{value}</div>
        </div>
    )
}
