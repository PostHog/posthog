import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { autoresearchPipelineLogic } from '../autoresearchPipelineLogic'
import { AutoresearchPipelineApi, ResearchIntervalDaysEnumApi } from '../generated/api.schemas'
import {
    MAX_ITERATIONS_PER_RUN,
    MIN_ITERATIONS_PER_RUN,
    trainingScheduleLogic,
    trainingScheduleStatus,
} from '../trainingScheduleLogic'
import { MetricCard } from './MetricCard'
import { PersonPropertySetting } from './PersonPropertySetting'
import { SectionCard } from './SectionCard'

const ONLY_WHEN_ASKED = 'only_when_asked'

const RESEARCH_INTERVAL_OPTIONS: { value: ResearchIntervalDaysEnumApi | typeof ONLY_WHEN_ASKED; label: string }[] = [
    ...Object.values(ResearchIntervalDaysEnumApi).map((days) => ({ value: days, label: `Every ${days} days` })),
    { value: ONLY_WHEN_ASKED, label: 'Only when I ask' },
]

export function SetupTab(): JSX.Element {
    const { pipeline } = useValues(autoresearchPipelineLogic)
    if (!pipeline) {
        return <LemonSkeleton className="h-40" />
    }
    return (
        <SectionCard
            title="Model definition"
            description={
                <>
                    Editing the target and populations in the UI is coming soon. For now, use the{' '}
                    <code>autoresearch</code> API or MCP tools, or recreate the model.
                </>
            }
        >
            <div className="@container">
                <div className="grid grid-cols-2 gap-3 @2xl:grid-cols-3">
                    <MetricCard label="Target event" value={pipeline.target_event} />
                    <MetricCard label="Prediction horizon" value={`${pipeline.horizon_days ?? '—'}d`} />
                    <MetricCard label="Training lookback" value={`${pipeline.training_lookback_days ?? '—'}d`} />
                </div>
            </div>
            <TrainingScheduleSetting pipeline={pipeline} />
            <PersonPropertySetting source="setup_tab" />
            <div>
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
        </SectionCard>
    )
}

function TrainingScheduleSetting({ pipeline }: { pipeline: AutoresearchPipelineApi }): JSX.Element {
    const { schedule, savingSchedule, saveDisabledReason } = useValues(trainingScheduleLogic({ id: pipeline.id }))
    const { setResearchIntervalDays, setIterationsPerRun, saveSchedule } = useActions(
        trainingScheduleLogic({ id: pipeline.id })
    )
    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1">
                    <span className="text-sm font-semibold">Look for a better model</span>
                    <LemonSelect
                        size="small"
                        options={RESEARCH_INTERVAL_OPTIONS}
                        value={schedule?.research_interval_days ?? ONLY_WHEN_ASKED}
                        onChange={(value) => setResearchIntervalDays(value === ONLY_WHEN_ASKED ? null : value)}
                        data-attr="autoresearch-research-interval"
                    />
                </label>
                <label className="flex flex-col gap-1">
                    <span className="text-sm font-semibold">Experiments per run</span>
                    <LemonInput
                        size="small"
                        type="number"
                        min={MIN_ITERATIONS_PER_RUN}
                        max={MAX_ITERATIONS_PER_RUN}
                        className="w-24"
                        value={schedule?.iterations_per_run}
                        onChange={(value) => setIterationsPerRun(value)}
                        data-attr="autoresearch-iterations-per-run"
                    />
                </label>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={saveSchedule}
                    loading={savingSchedule}
                    disabledReason={saveDisabledReason}
                    data-attr="autoresearch-training-schedule-save"
                >
                    Save schedule
                </LemonButton>
            </div>
            <p className="text-xs text-secondary mb-0">{trainingScheduleStatus(pipeline)}</p>
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
