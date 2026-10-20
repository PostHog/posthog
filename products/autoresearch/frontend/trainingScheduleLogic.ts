import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { AutoresearchPipelineLogicProps, autoresearchPipelineLogic } from './autoresearchPipelineLogic'
import { autoresearchPartialUpdate } from './generated/api'
import type { AutoresearchPipelineApi, ResearchIntervalDaysEnumApi } from './generated/api.schemas'

export const MIN_ITERATIONS_PER_RUN = 1
export const MAX_ITERATIONS_PER_RUN = 50

export interface TrainingScheduleDraft {
    research_interval_days: ResearchIntervalDaysEnumApi | null
    iterations_per_run: number | undefined
}

/** One line on what training does next, from the saved schedule. */
export function trainingScheduleStatus(pipeline: AutoresearchPipelineApi, now: dayjs.Dayjs = dayjs()): string {
    if (pipeline.research_interval_days === null || !pipeline.next_research_at) {
        return 'Training starts only when you ask for it.'
    }
    if (pipeline.training_phase === 'explore') {
        return 'Exploring: training on each scoring day until a run stops improving the model.'
    }
    const next = dayjs(pipeline.next_research_at)
    if (!next.isAfter(now)) {
        return 'Next research run on the next scoring day.'
    }
    return `Next research run on ${next.format('MMM D')}.`
}

export interface trainingScheduleLogicValues {
    currentTeamId: number | null
    pipeline: AutoresearchPipelineApi | null
    draft: Partial<TrainingScheduleDraft>
    savingSchedule: boolean
    schedule: TrainingScheduleDraft | null
    saveDisabledReason: string | undefined
}

export interface trainingScheduleLogicActions {
    loadPipelineSuccess: (pipeline: AutoresearchPipelineApi | null) => {
        pipeline: AutoresearchPipelineApi | null
        payload?: any
    }
    setResearchIntervalDays: (days: ResearchIntervalDaysEnumApi | null) => {
        days: ResearchIntervalDaysEnumApi | null
    }
    setIterationsPerRun: (iterations: number | undefined) => { iterations: number | undefined }
    resetDraft: () => { value: true }
    saveSchedule: () => { value: true }
    saveScheduleFinished: () => { value: true }
}

export type trainingScheduleLogicType = MakeLogicType<
    trainingScheduleLogicValues,
    trainingScheduleLogicActions,
    AutoresearchPipelineLogicProps
>

export const trainingScheduleLogic = kea<trainingScheduleLogicType>([
    props({} as AutoresearchPipelineLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'autoresearch', 'frontend', 'trainingScheduleLogic', key]),
    connect((props: AutoresearchPipelineLogicProps) => ({
        values: [teamLogic, ['currentTeamId'], autoresearchPipelineLogic(props), ['pipeline']],
        actions: [autoresearchPipelineLogic(props), ['loadPipelineSuccess']],
    })),
    actions({
        setResearchIntervalDays: (days: ResearchIntervalDaysEnumApi | null) => ({ days }),
        setIterationsPerRun: (iterations: number | undefined) => ({ iterations }),
        resetDraft: true,
        saveSchedule: true,
        saveScheduleFinished: true,
    }),
    reducers({
        // The unsaved edits. A field that is not here shows its saved value.
        draft: [
            {} as Partial<TrainingScheduleDraft>,
            {
                setResearchIntervalDays: (state, { days }) => ({ ...state, research_interval_days: days }),
                setIterationsPerRun: (state, { iterations }) => ({ ...state, iterations_per_run: iterations }),
                resetDraft: () => ({}),
            },
        ],
        savingSchedule: [
            false,
            {
                saveSchedule: () => true,
                saveScheduleFinished: () => false,
            },
        ],
    }),
    selectors({
        schedule: [
            (s) => [s.pipeline, s.draft],
            (pipeline: AutoresearchPipelineApi | null, draft: Partial<TrainingScheduleDraft>) =>
                pipeline ? { ...pickSchedule(pipeline), ...draft } : null,
        ],
        saveDisabledReason: [
            (s) => [s.pipeline, s.schedule, s.savingSchedule],
            (
                pipeline: AutoresearchPipelineApi | null,
                schedule: TrainingScheduleDraft | null,
                savingSchedule: boolean
            ): string | undefined => {
                if (savingSchedule) {
                    return 'The schedule is saving'
                }
                if (!pipeline || !schedule) {
                    return 'The model is loading'
                }
                const iterations = schedule.iterations_per_run
                if (
                    iterations === undefined ||
                    !Number.isInteger(iterations) ||
                    iterations < MIN_ITERATIONS_PER_RUN ||
                    iterations > MAX_ITERATIONS_PER_RUN
                ) {
                    return `Enter ${MIN_ITERATIONS_PER_RUN} to ${MAX_ITERATIONS_PER_RUN} experiments per run`
                }
                const saved = pickSchedule(pipeline)
                if (
                    saved.iterations_per_run === iterations &&
                    saved.research_interval_days === schedule.research_interval_days
                ) {
                    return 'Change a setting to save'
                }
                return undefined
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        saveSchedule: async () => {
            const { schedule, currentTeamId } = values
            if (!schedule || schedule.iterations_per_run === undefined || !currentTeamId) {
                actions.saveScheduleFinished()
                return
            }
            const changes = {
                research_interval_days: schedule.research_interval_days,
                iterations_per_run: schedule.iterations_per_run,
            }
            try {
                actions.loadPipelineSuccess(await autoresearchPartialUpdate(String(currentTeamId), props.id, changes))
                actions.resetDraft()
                posthog.capture('autoresearch training schedule changed', { pipeline_id: props.id, ...changes })
                lemonToast.success('Training schedule saved.')
            } catch {
                posthog.capture('autoresearch model action failed', {
                    action: 'training_schedule',
                    pipeline_id: props.id,
                })
                lemonToast.error("Couldn't save the training schedule. Try again.")
            } finally {
                actions.saveScheduleFinished()
            }
        },
    })),
])

function pickSchedule(pipeline: AutoresearchPipelineApi): TrainingScheduleDraft {
    return {
        research_interval_days: pipeline.research_interval_days,
        iterations_per_run: pipeline.iterations_per_run,
    }
}
