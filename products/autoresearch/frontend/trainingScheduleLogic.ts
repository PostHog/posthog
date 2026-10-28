import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'

import { AutoresearchPipelineLogicProps, autoresearchPipelineLogic } from './autoresearchPipelineLogic'
import { autoresearchAgentModelsRetrieve, autoresearchPartialUpdate } from './generated/api'
import type {
    AgentModelOptionsApi,
    AgentReasoningEffortOptionApi,
    AutoresearchPipelineApi,
    ResearchIntervalDaysEnumApi,
} from './generated/api.schemas'

export const MIN_ITERATIONS_PER_RUN = 1
export const MAX_ITERATIONS_PER_RUN = 50

export interface TrainingScheduleDraft {
    research_interval_days: ResearchIntervalDaysEnumApi | null
    iterations_per_run: number | undefined
    // Null means the autoresearch default.
    agent_model: string | null
    agent_reasoning_effort: string | null
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
    agentModelOptions: AgentModelOptionsApi | null
    agentModelOptionsLoading: boolean
    effortOptions: AgentReasoningEffortOptionApi[]
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
    setAgentModel: (model: string | null) => { model: string | null }
    setAgentReasoningEffort: (effort: string | null) => { effort: string | null }
    loadAgentModelOptions: () => { value: true }
    loadAgentModelOptionsSuccess: (agentModelOptions: AgentModelOptionsApi | null) => {
        agentModelOptions: AgentModelOptionsApi | null
        payload?: any
    }
    loadAgentModelOptionsFailure: (error: string) => { error: string }
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
        setAgentModel: (model: string | null) => ({ model }),
        setAgentReasoningEffort: (effort: string | null) => ({ effort }),
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
                // Efforts differ per model, so a new model starts from its default effort.
                setAgentModel: (state, { model }) => ({ ...state, agent_model: model, agent_reasoning_effort: null }),
                setAgentReasoningEffort: (state, { effort }) => ({ ...state, agent_reasoning_effort: effort }),
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
    loaders(({ values }) => ({
        agentModelOptions: [
            null as AgentModelOptionsApi | null,
            {
                loadAgentModelOptions: async () => {
                    if (!values.currentTeamId) {
                        return null
                    }
                    return autoresearchAgentModelsRetrieve(String(values.currentTeamId))
                },
            },
        ],
    })),
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
                    saved.research_interval_days === schedule.research_interval_days &&
                    saved.agent_model === schedule.agent_model &&
                    saved.agent_reasoning_effort === schedule.agent_reasoning_effort
                ) {
                    return 'Change a setting to save'
                }
                return undefined
            },
        ],
        effortOptions: [
            (s) => [s.agentModelOptions, s.schedule],
            (
                agentModelOptions: AgentModelOptionsApi | null,
                schedule: TrainingScheduleDraft | null
            ): AgentReasoningEffortOptionApi[] => {
                if (!agentModelOptions) {
                    return []
                }
                const model = schedule?.agent_model ?? agentModelOptions.default_model
                return agentModelOptions.models.find((option) => option.model === model)?.supported_efforts ?? []
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
            const scheduleChanges = {
                research_interval_days: schedule.research_interval_days,
                iterations_per_run: schedule.iterations_per_run,
            }
            const modelChanges = {
                agent_model: schedule.agent_model,
                agent_reasoning_effort: schedule.agent_reasoning_effort,
            }
            const saved = values.pipeline ? pickSchedule(values.pipeline) : null
            const scheduleChanged =
                saved?.research_interval_days !== scheduleChanges.research_interval_days ||
                saved?.iterations_per_run !== scheduleChanges.iterations_per_run
            const modelChanged =
                saved?.agent_model !== modelChanges.agent_model ||
                saved?.agent_reasoning_effort !== modelChanges.agent_reasoning_effort
            try {
                actions.loadPipelineSuccess(
                    await autoresearchPartialUpdate(String(currentTeamId), props.id, {
                        ...scheduleChanges,
                        ...modelChanges,
                    })
                )
                actions.resetDraft()
                // pinned: analytics event names. Renaming breaks insights built on them.
                if (scheduleChanged) {
                    posthog.capture('autoresearch training schedule changed', {
                        pipeline_id: props.id,
                        ...scheduleChanges,
                    })
                }
                if (modelChanged) {
                    posthog.capture('autoresearch research model changed', { pipeline_id: props.id, ...modelChanges })
                }
                lemonToast.success('Training settings saved.')
            } catch {
                posthog.capture('autoresearch model action failed', {
                    action: 'training_schedule',
                    pipeline_id: props.id,
                })
                lemonToast.error("Couldn't save the training settings. Try again.")
            } finally {
                actions.saveScheduleFinished()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadAgentModelOptions()
    }),
])

function pickSchedule(pipeline: AutoresearchPipelineApi): TrainingScheduleDraft {
    return {
        research_interval_days: pipeline.research_interval_days,
        iterations_per_run: pipeline.iterations_per_run,
        agent_model: pipeline.agent_model,
        agent_reasoning_effort: pipeline.agent_reasoning_effort,
    }
}
