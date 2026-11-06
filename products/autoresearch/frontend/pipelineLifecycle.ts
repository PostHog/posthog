import { dayjs } from 'lib/dayjs'
import { pluralize } from 'lib/utils/strings'

import { AutoresearchModelApi, AutoresearchPipelineApi, AutoresearchRunApi } from './generated/api.schemas'

export type LifecycleStepKey = 'question_set' | 'agent_searched' | 'model_live' | 'scoring' | 'checked'

export type LifecycleStepState = 'done' | 'current' | 'upcoming'

export interface LifecycleStep {
    key: LifecycleStepKey
    label: string
    detail: string
    state: LifecycleStepState
}

export interface LifecycleInput {
    pipeline: Pick<
        AutoresearchPipelineApi,
        'created_at' | 'horizon_days' | 'last_scored_at' | 'training_run_count' | 'experiment_count'
    > & { live_training_run: unknown }
    champion: Pick<AutoresearchModelApi, 'is_preliminary' | 'promoted_at'> | null
    runs: Pick<AutoresearchRunApi, 'run_type' | 'status' | 'created_at' | 'rows_scored' | 'metrics'>[]
    /** Prediction dates (YYYY-MM-DD) that a validation run checked against real outcomes. */
    validatedDates: string[]
    now: dayjs.Dayjs
}

/** The date a scoring run predicts for. Validation groups runs by this date, so it is the date to count. */
function predictionDate(run: LifecycleInput['runs'][number]): string {
    const recorded = run.metrics?.prediction_date
    return typeof recorded === 'string' ? recorded : dayjs(run.created_at).utc().format('YYYY-MM-DD')
}

/** Scored dates whose prediction horizon has passed, so their real outcomes are known. */
function maturedScoredDates(
    runs: LifecycleInput['runs'],
    horizonDays: number | undefined,
    now: dayjs.Dayjs
): Set<string> {
    const cutoff = now.subtract(horizonDays ?? 0, 'day')
    const dates = new Set<string>()
    for (const run of runs) {
        // A run that scored nobody emits no predictions, so validation has nothing to check for its date.
        if (run.run_type !== 'inference' || run.status !== 'completed' || !run.rows_scored) {
            continue
        }
        const date = predictionDate(run)
        if (!dayjs.utc(date).isAfter(cutoff)) {
            dates.add(date)
        }
    }
    return dates
}

function checkedDetail(input: LifecycleInput): string {
    const validated = new Set(input.validatedDates).size
    const matured = Math.max(maturedScoredDates(input.runs, input.pipeline.horizon_days, input.now).size, validated)
    if (matured === 0) {
        return input.pipeline.last_scored_at
            ? `First check ${pluralize(input.pipeline.horizon_days ?? 0, 'day')} after scoring`
            : 'Not yet'
    }
    return `${validated} of ${pluralize(matured, 'matured date')} checked`
}

/** Where a model is in its lifecycle. The first step that is not done is the current step. */
export function pipelineLifecycle(input: LifecycleInput): LifecycleStep[] {
    const { pipeline, champion } = input
    const searching = pipeline.live_training_run != null
    const steps: Omit<LifecycleStep, 'state'>[] = [
        {
            key: 'question_set',
            label: 'Question set',
            detail: dayjs(pipeline.created_at).format('MMM D, YYYY'),
        },
        {
            key: 'agent_searched',
            label: 'Agent searched',
            detail:
                pipeline.training_run_count > 0
                    ? `${pluralize(pipeline.training_run_count, 'run')} · ${pluralize(pipeline.experiment_count, 'experiment')}`
                    : 'Not started',
        },
        {
            key: 'model_live',
            label: 'Best model live',
            detail: !champion
                ? 'Not yet'
                : champion.is_preliminary
                  ? 'Preliminary'
                  : champion.promoted_at
                    ? dayjs(champion.promoted_at).format('MMM D, YYYY')
                    : 'Live',
        },
        {
            key: 'scoring',
            label: 'Scoring on schedule',
            detail: pipeline.last_scored_at ? `Last run ${dayjs(pipeline.last_scored_at).fromNow()}` : 'Not yet',
        },
        {
            key: 'checked',
            label: 'Checked against reality',
            detail: checkedDetail(input),
        },
    ]
    const done: Record<LifecycleStepKey, boolean> = {
        question_set: true,
        // A failed attempt counts as a run but records no experiments, so it is not a search.
        agent_searched: champion != null || (pipeline.experiment_count > 0 && !searching),
        model_live: champion != null,
        scoring: pipeline.last_scored_at != null,
        checked: input.validatedDates.length > 0,
    }
    const currentIndex = steps.findIndex((step) => !done[step.key])
    return steps.map((step, index) => ({
        ...step,
        state: done[step.key] ? 'done' : index === currentIndex ? 'current' : 'upcoming',
    }))
}
