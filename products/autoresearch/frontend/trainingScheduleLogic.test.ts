import { dayjs } from 'lib/dayjs'

import type { AutoresearchPipelineApi, ProjectLimitsApi } from './generated/api.schemas'
import {
    notPromotedReasonSentence,
    trainingDisabledByLimitReason,
    trainingScheduleStatus,
} from './trainingScheduleLogic'

const NOW = dayjs('2026-03-01T12:00:00Z')

const LIMITS: ProjectLimitsApi = {
    max_training_runs_per_day: 3,
    training_runs_used: 1,
    next_slot_at: null,
    max_iterations_per_run: 10,
    max_live_pipelines: 3,
    live_pipelines: 1,
    max_training_runs_per_day_source: 'code',
    max_iterations_per_run_source: 'code',
    max_live_pipelines_source: 'code',
}

const PIPELINE = {
    status: 'running',
    research_interval_days: 7,
    training_phase: 'maintain',
    next_research_at: '2026-03-05T00:00:00Z',
    champion_holdout_auc: 0.8,
    champion_realized_auc: null,
} as AutoresearchPipelineApi

const NO_LIVE_MODEL = {
    ...PIPELINE,
    status: 'bootstrapping',
    training_phase: 'explore',
    champion_holdout_auc: null,
} as AutoresearchPipelineApi

describe('trainingScheduleLogic limits', () => {
    it.each<[string, Partial<ProjectLimitsApi>, string]>([
        ['a slot is free', {}, 'Next research run on Mar 5.'],
        [
            'the project is at its daily limit',
            { training_runs_used: 3, next_slot_at: '2026-03-01T15:30:00Z' },
            `This project is at its daily limit of 3 training runs. The next run can start at ${dayjs('2026-03-01T15:30:00Z').format('MMM D, h:mm A')}.`,
        ],
        [
            'training is turned off',
            { max_training_runs_per_day: 0, training_runs_used: 0 },
            'Training is turned off for this project. Contact support to turn it on.',
        ],
    ])('status line when %s', (_name, overrides, expected) => {
        expect(trainingScheduleStatus(PIPELINE, { ...LIMITS, ...overrides }, NOW)).toEqual(expected)
    })

    it.each<[string, AutoresearchPipelineApi, string]>([
        [
            'a live model exploring',
            { ...PIPELINE, training_phase: 'explore' },
            'Exploring: training on each scoring day until a run stops improving the model.',
        ],
        ['a model with no live version', NO_LIVE_MODEL, 'Next research run on Mar 5.'],
        [
            'a model with no live version past its due date',
            { ...NO_LIVE_MODEL, next_research_at: '2026-02-20T00:00:00Z' },
            'Next research run on the next scoring day.',
        ],
    ])('status line for %s', (_name, pipeline, expected) => {
        expect(trainingScheduleStatus(pipeline, LIMITS, NOW)).toEqual(expected)
    })

    it.each([
        [
            'The champion fit failed: model.pkl is 14830476 bytes, over the 10485760-byte cap',
            'The model file was too large to run every day.',
        ],
        [
            "features.sql took 412s against today's inference anchors, above the 300s budget for a scoring run",
            "The model's daily query took too long to run.",
        ],
        [
            "features.sql failed against today's inference anchors: Code: 159. Timeout exceeded: elapsed 300 seconds",
            "The model's daily query took too long to run.",
        ],
        ['The champion fit failed: predict.py exited with code 1', 'The model failed a check before going live.'],
    ])('plain sentence for not promoted reason %s', (reason, expected) => {
        expect(notPromotedReasonSentence(reason)).toEqual(expected)
    })

    it.each<[string, AutoresearchPipelineApi['status'], Partial<ProjectLimitsApi>, boolean]>([
        ['a draft at the active model limit', 'draft', { live_pipelines: 3 }, true],
        ['a live model retraining at the active model limit', 'running', { live_pipelines: 3 }, false],
        ['a draft under the active model limit', 'draft', {}, false],
    ])('train is disabled for %s', (_name, status, overrides, disabled) => {
        const reason = trainingDisabledByLimitReason({ ...PIPELINE, status }, { ...LIMITS, ...overrides })
        expect(reason !== undefined).toBe(disabled)
    })
})
