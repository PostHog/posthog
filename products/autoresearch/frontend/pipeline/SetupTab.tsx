import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchPipelineApi } from '../generated/api.schemas'
import { MetricCard } from './MetricCard'

export function SetupTab(): JSX.Element {
    const { pipeline } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }
    return (
        <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <MetricCard label="Target event" value={pipeline.target_event} />
                <MetricCard label="Prediction horizon" value={`${pipeline.horizon_days ?? '—'}d`} />
                <MetricCard label="Training lookback" value={`${pipeline.training_lookback_days ?? '—'}d`} />
                <MetricCard
                    label="Budget remaining"
                    value={`${pipeline.iteration_budget_remaining} / ${pipeline.iteration_budget ?? '—'}`}
                />
            </div>
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
