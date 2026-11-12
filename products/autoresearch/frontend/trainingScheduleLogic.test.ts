import { dayjs } from 'lib/dayjs'

import type { AutoresearchPipelineApi, ProjectLimitsApi } from './generated/api.schemas'
import { trainingScheduleStatus, trainingDisabledByLimitReason } from './trainingScheduleLogic'

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

    it.each<[string, AutoresearchPipelineApi['status'], Partial<ProjectLimitsApi>, boolean]>([
        ['a draft at the active model limit', 'draft', { live_pipelines: 3 }, true],
        ['a live model retraining at the active model limit', 'running', { live_pipelines: 3 }, false],
        ['a draft under the active model limit', 'draft', {}, false],
    ])('train is disabled for %s', (_name, status, overrides, disabled) => {
        const reason = trainingDisabledByLimitReason({ ...PIPELINE, status }, { ...LIMITS, ...overrides })
        expect(reason !== undefined).toBe(disabled)
    })
})
