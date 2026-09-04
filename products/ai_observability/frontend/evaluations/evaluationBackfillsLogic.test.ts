import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    evaluationsBackfillsCancelCreate,
    evaluationsBackfillsCreate,
    evaluationsBackfillsEstimateCreate,
    evaluationsBackfillsList,
} from '../generated/api'
import type { EvaluationBackfillApi, EvaluationBackfillEstimateApi } from '../generated/api.schemas'
import { evaluationBackfillsLogic } from './evaluationBackfillsLogic'

jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    evaluationsBackfillsList: jest.fn(),
    evaluationsBackfillsCreate: jest.fn(),
    evaluationsBackfillsEstimateCreate: jest.fn(),
    evaluationsBackfillsCancelCreate: jest.fn(),
}))

const listMock = jest.mocked(evaluationsBackfillsList)
const createMock = jest.mocked(evaluationsBackfillsCreate)
const estimateMock = jest.mocked(evaluationsBackfillsEstimateCreate)
const cancelMock = jest.mocked(evaluationsBackfillsCancelCreate)

const EVALUATION_ID = 'eval-123'

const mockEvaluation = {
    id: EVALUATION_ID,
    name: 'Test Evaluation',
    description: '',
    directory_id: null,
    enabled: true,
    status: 'active',
    status_reason: null,
    status_reason_detail: null,
    evaluation_type: 'llm_judge',
    evaluation_config: { prompt: 'Is it helpful?' },
    output_type: 'boolean',
    output_config: {},
    conditions: [
        {
            id: 'cond-1',
            rollout_percentage: 50,
            properties: [{ key: '$ai_model', value: 'gpt-5', operator: 'exact', type: 'event' }],
            // The stored condition carries compiled state the backfill API does not accept.
            bytecode: ['_H', 1],
        },
    ],
    target: 'generation',
    target_config: {},
    model_configuration: null,
    total_runs: 0,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
}

function backfill(overrides: Partial<EvaluationBackfillApi> = {}): EvaluationBackfillApi {
    return {
        id: 'backfill-1',
        status: 'completed',
        target: 'generation',
        window_start: '2024-01-01T00:00:00Z',
        window_end: '2024-01-02T00:00:00Z',
        conditions: [{ properties: [], rollout_percentage: 100 }],
        rerun_existing: false,
        total_count: 10,
        dispatched_count: 8,
        skipped_count: 2,
        created_by: null,
        created_at: '2024-01-02T00:00:00Z',
        finished_at: '2024-01-02T01:00:00Z',
        ...overrides,
    }
}

function estimate(overrides: Partial<EvaluationBackfillEstimateApi> = {}): EvaluationBackfillEstimateApi {
    return {
        total_units: 42,
        unit: 'generation',
        window_start: '2024-01-01T00:00:00Z',
        window_end: '2024-01-08T00:00:00Z',
        ...overrides,
    }
}

function wait(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

describe('evaluationBackfillsLogic', () => {
    let logic: ReturnType<typeof evaluationBackfillsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:teamId/llm_analytics/provider_keys/': { results: [] },
                '/api/environments/:teamId/llm_analytics/evaluation_config/': {
                    active_provider_key: null,
                    created_at: '2024-01-01T00:00:00Z',
                    updated_at: '2024-01-01T00:00:00Z',
                },
                '/api/projects/:teamId/evaluations/:id/': mockEvaluation,
            },
        })
        initKeaTests()
        listMock.mockReset().mockResolvedValue({ count: 0, results: [] })
        createMock.mockReset().mockResolvedValue(backfill({ status: 'running' }))
        estimateMock.mockReset().mockResolvedValue(estimate())
        cancelMock.mockReset().mockResolvedValue(backfill({ status: 'cancelled' }))
    })

    afterEach(() => {
        logic?.unmount()
    })

    function mountLogic(): ReturnType<typeof evaluationBackfillsLogic.build> {
        logic = evaluationBackfillsLogic({ evaluationId: EVALUATION_ID })
        logic.mount()
        return logic
    }

    /** The tab opens on a default range and counts it once, so most cases start from that count. */
    async function mountAndSettle(): Promise<void> {
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadBackfillsSuccess', 'requestEstimateSuccess'])
        estimateMock.mockClear()
    }

    it('seeds conditions from the evaluation, strips keys the backfill API rejects, then counts the default range', async () => {
        const seededConditions = [
            {
                id: 'cond-1',
                rollout_percentage: 50,
                properties: [{ key: '$ai_model', value: 'gpt-5', operator: 'exact', type: 'event' }],
            },
        ]
        mountLogic()

        await expectLogic(logic).toDispatchActions(['requestEstimateSuccess']).toMatchValues({
            conditions: seededConditions,
            windowDateFrom: '-7d',
            windowDateTo: null,
        })

        // One count, and it uses the seeded conditions rather than the empty list held before load.
        expect(estimateMock).toHaveBeenCalledTimes(1)
        expect(estimateMock.mock.calls[0][2]).toEqual({
            window_start: dayjs().tz('UTC').startOf('day').subtract(7, 'day').toISOString(),
            window_end: expect.any(String),
            conditions: seededConditions,
            rerun_existing: false,
        })
    })

    it('debounces estimate requests and drops a stale response', async () => {
        await mountAndSettle()

        // Two changes inside the debounce window make one request, for the range picked last.
        logic.actions.setWindowRange('-30d', null)
        logic.actions.setWindowRange('-7d', null)
        await expectLogic(logic).toDispatchActions(['requestEstimateSuccess'])
        expect(estimateMock).toHaveBeenCalledTimes(1)

        // A response that arrives after a newer request started must not land.
        let resolveStale: (value: EvaluationBackfillEstimateApi) => void = () => {}
        estimateMock.mockReturnValueOnce(
            new Promise<EvaluationBackfillEstimateApi>((resolve) => {
                resolveStale = resolve
            })
        )
        estimateMock.mockResolvedValueOnce(estimate({ total_units: 7 }))

        logic.actions.setWindowRange('-14d', null)
        await wait(400)
        logic.actions.setWindowRange('-24h', null)
        await expectLogic(logic).toDispatchActions(['requestEstimateSuccess'])

        resolveStale(estimate({ total_units: 999 }))
        await wait(50)

        await expectLogic(logic).toMatchValues({ estimate: expect.objectContaining({ total_units: 7 }) })
    })

    it.each([
        ['no estimate yet', null, false, 'Pick a time range to see how many units match'],
        ['an empty estimate', 0, false, 'Nothing in this range matches these conditions'],
        ['a running backfill', 42, true, 'This evaluation already has a running backfill'],
        ['a usable estimate', 42, false, undefined],
    ])(
        'reports the start button as blocked by %s',
        async (_name, totalUnits: number | null, running: boolean, expected: string | undefined) => {
            listMock.mockResolvedValue({
                count: running ? 1 : 0,
                results: running ? [backfill({ status: 'running' })] : [],
            })
            await mountAndSettle()

            if (totalUnits === null) {
                // Clearing the range is how a user gets back to having no count.
                logic.actions.setWindowRange(null, null)
                await expectLogic(logic).toDispatchActions(['requestEstimateFailure'])
            } else {
                logic.actions.requestEstimateSuccess(estimate({ total_units: totalUnits }))
            }

            await expectLogic(logic).toMatchValues({ startDisabledReason: expected })
        }
    )

    it('says it is counting while an estimate is in flight, then surfaces the failure', async () => {
        await mountAndSettle()

        estimateMock.mockRejectedValueOnce(new Error('Window too large'))
        logic.actions.setWindowRange('-14d', null)

        // An in-flight count must not read as "no range picked yet".
        await expectLogic(logic).toMatchValues({ startDisabledReason: 'Counting matching units' })

        await expectLogic(logic).toDispatchActions(['requestEstimateFailure'])
        await expectLogic(logic).toMatchValues({
            estimateError: 'Window too large',
            startDisabledReason: 'Window too large',
        })
    })

    it('stops counting when the estimate is requested with no range picked', async () => {
        await mountAndSettle()

        logic.actions.setWindowRange(null, null)

        await expectLogic(logic).toDispatchActions(['requestEstimateFailure']).toMatchValues({
            estimateLoading: false,
            estimateError: null,
            startDisabledReason: 'Pick a time range to see how many units match',
        })
        expect(estimateMock).not.toHaveBeenCalled()
    })

    it('anchors a relative preset on the project timezone', async () => {
        const timezone = 'America/New_York'
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, timezone })
        await mountAndSettle()

        logic.actions.setWindowRange('-7d', null)
        await expectLogic(logic).toDispatchActions(['requestEstimateSuccess'])

        const body = estimateMock.mock.calls[estimateMock.mock.calls.length - 1][2]
        expect(body.window_start).toEqual(dayjs().tz(timezone).startOf('day').subtract(7, 'day').toISOString())
        expect(Math.abs(dayjs(body.window_end).diff(dayjs(), 'second'))).toBeLessThan(5)
    })

    it('polls the list while a backfill is running and stops once none is', async () => {
        listMock.mockResolvedValueOnce({ count: 1, results: [backfill({ status: 'running' })] })
        mountLogic()

        await expectLogic(logic).toDispatchActions(['loadBackfillsSuccess'])
        expect(logic.cache.disposables.registry.has('backfillPoll')).toBe(true)

        listMock.mockResolvedValue({ count: 1, results: [backfill({ status: 'completed' })] })
        logic.actions.loadBackfills(true)

        await expectLogic(logic).toDispatchActions(['loadBackfillsSuccess'])
        expect(logic.cache.disposables.registry.has('backfillPoll')).toBe(false)
    })

    it('sends the clamped window, the edited conditions and the rerun flag on create', async () => {
        await mountAndSettle()

        logic.actions.setConditions([{ id: 'cond-1', rollout_percentage: 10, properties: [] }])
        logic.actions.setRerunExisting(true)
        logic.actions.requestEstimateSuccess(
            estimate({ window_start: '2024-02-01T00:00:00Z', window_end: '2024-02-08T00:00:00Z' })
        )

        logic.actions.createBackfill()
        await expectLogic(logic).toDispatchActions(['createBackfillDone'])

        expect(createMock).toHaveBeenCalledWith(expect.any(String), EVALUATION_ID, {
            window_start: '2024-02-01T00:00:00Z',
            window_end: '2024-02-08T00:00:00Z',
            conditions: [{ id: 'cond-1', rollout_percentage: 10, properties: [] }],
            rerun_existing: true,
        })
        // The estimate belongs to the window that was just started, so it should not linger.
        await expectLogic(logic).toMatchValues({ estimate: null })
    })

    it('keeps the counted window on screen when create fails', async () => {
        await mountAndSettle()

        logic.actions.requestEstimateSuccess(estimate())
        createMock.mockRejectedValueOnce(new Error('nope'))

        logic.actions.createBackfill()
        await expectLogic(logic).toDispatchActions(['createBackfillDone'])

        await expectLogic(logic).toMatchValues({
            creatingBackfill: false,
            estimate: expect.objectContaining({ total_units: 42 }),
        })
    })

    it('cancels a backfill and reloads the list', async () => {
        listMock.mockResolvedValue({ count: 1, results: [backfill({ status: 'running' })] })
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadBackfillsSuccess'])

        logic.actions.cancelBackfill('backfill-1')
        await expectLogic(logic).toMatchValues({ transitioningIds: ['backfill-1'] })
        await expectLogic(logic).toDispatchActions(['transitionBackfillDone'])

        expect(cancelMock).toHaveBeenCalledWith(expect.any(String), EVALUATION_ID, 'backfill-1')
        await expectLogic(logic).toMatchValues({ transitioningIds: [] })
    })
})
