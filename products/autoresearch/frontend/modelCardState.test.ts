import { dayjs } from 'lib/dayjs'

import { AutoresearchPipelineApi } from './generated/api.schemas'
import { firstCheckCountdown, modelCardState } from './modelCardState'

describe('modelCardState', () => {
    const liveRun: AutoresearchPipelineApi['live_training_run'] = {
        id: 'run-1',
        iteration_budget: 8,
        experiment_count: 2,
        best_holdout_score: 0.72,
        latest_agent_description: 'baseline',
    }
    const noChampion = { champion_holdout_auc: null, champion_realized_auc: null, champion_is_preliminary: null }
    const awaiting = { champion_holdout_auc: 0.81, champion_realized_auc: null, champion_is_preliminary: null }
    const confirmed = { champion_holdout_auc: 0.81, champion_realized_auc: 0.78, champion_is_preliminary: false }

    test.each([
        { name: 'draft', status: 'draft' as const, live: false, champion: noChampion, expected: 'draft' },
        {
            name: 'draft with a live run',
            status: 'draft' as const,
            live: true,
            champion: noChampion,
            expected: 'training',
        },
        {
            name: 'first training run',
            status: 'bootstrapping' as const,
            live: false,
            champion: noChampion,
            expected: 'training',
        },
        {
            name: 'no realized AUC',
            status: 'running' as const,
            live: false,
            champion: awaiting,
            expected: 'awaiting_check',
        },
        {
            name: 'preliminary realized AUC',
            status: 'running' as const,
            live: false,
            champion: { ...confirmed, champion_is_preliminary: true },
            expected: 'awaiting_check',
        },
        { name: 'realized AUC', status: 'paused' as const, live: false, champion: confirmed, expected: 'confirmed' },
        {
            name: 'retrain of a confirmed model',
            status: 'running' as const,
            live: true,
            champion: confirmed,
            expected: 'confirmed',
        },
        {
            name: 'retrain before the first check',
            status: 'running' as const,
            live: true,
            champion: awaiting,
            expected: 'awaiting_check',
        },
    ])('$name is $expected', ({ status, live, champion, expected }) => {
        expect(modelCardState({ status, live_training_run: live ? liveRun : null, ...champion })).toEqual(expected)
    })
})

describe('firstCheckCountdown', () => {
    const now = dayjs('2026-03-10T12:00:00Z')

    test.each([
        {
            name: 'short horizon counts days',
            checkAt: '2026-03-13T01:00:00Z',
            horizon: 7,
            label: 'First real check in 3\u00a0days',
        },
        {
            name: 'part of a day rounds up',
            checkAt: '2026-03-10T13:00:00Z',
            horizon: 7,
            label: 'First real check in 1\u00a0day',
        },
        {
            name: 'long horizon shows the date',
            checkAt: '2026-03-30T01:00:00Z',
            horizon: 30,
            label: 'First real check on Mar 30',
        },
        { name: 'a past date is due', checkAt: '2026-03-09T01:00:00Z', horizon: 7, label: 'First real check is due' },
    ])('$name', ({ checkAt, horizon, label }) => {
        expect(firstCheckCountdown(checkAt, horizon, now).label).toEqual(label)
    })

    test.each([
        { checkAt: '2026-03-17T12:00:00Z', horizon: 7, percent: 0 },
        { checkAt: '2026-03-14T00:00:00Z', horizon: 7, percent: 50 },
        { checkAt: '2026-03-01T00:00:00Z', horizon: 7, percent: 100 },
    ])('percent of the window passed is $percent', ({ checkAt, horizon, percent }) => {
        expect(firstCheckCountdown(checkAt, horizon, now).percent).toBeCloseTo(percent)
    })
})
