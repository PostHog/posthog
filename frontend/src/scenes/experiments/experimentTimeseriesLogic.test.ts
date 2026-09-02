import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import { useMocks } from '~/mocks/jest'
import { ExperimentMetric } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { TimeseriesDisplayState, experimentTimeseriesLogic } from './experimentTimeseriesLogic'

const EXPERIMENT = experimentJson as unknown as Experiment
const METRIC = { kind: 'ExperimentMetric', uuid: 'metric-uuid', fingerprint: 'fp-1' } as unknown as ExperimentMetric
const TIMESERIES_URL = '/api/projects/:team_id/experiments/:id/timeseries_results/'

describe('experimentTimeseriesLogic', () => {
    let logic: ReturnType<typeof experimentTimeseriesLogic.build>

    beforeEach(async () => {
        initKeaTests()
        await expectLogic(teamLogic).toMatchValues({ currentProjectId: expect.any(Number) })
    })

    afterEach(() => {
        logic?.unmount()
    })

    const cases: [string, Record<string, any>, TimeseriesDisplayState][] = [
        ['completed with data', { status: 'completed', timeseries: { '2026-01-01': { x: 1 } }, errors: null }, 'data'],
        [
            'partial with data',
            { status: 'partial', timeseries: { '2026-01-01': { x: 1 }, '2026-01-02': null }, errors: null },
            'data',
        ],
        [
            'failed calculation',
            { status: 'failed', timeseries: { '2026-01-01': null }, errors: { '2026-01-01': 'boom' } },
            'failed',
        ],
        ['not computed yet', { status: 'pending', timeseries: { '2026-01-01': null }, errors: null }, 'pending'],
    ]

    it.each(cases)('classifies a %s payload', async (_name, payload, expected) => {
        useMocks({ get: { [TIMESERIES_URL]: () => [200, payload] } })
        logic = experimentTimeseriesLogic({ experiment: EXPERIMENT, metric: METRIC })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadTimeseriesSuccess'])
            .toMatchValues({ timeseriesDisplayState: expected })
    })

    it('classifies a failed request as the error state', async () => {
        useMocks({ get: { [TIMESERIES_URL]: () => [500, {}] } })
        logic = experimentTimeseriesLogic({ experiment: EXPERIMENT, metric: METRIC })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadTimeseriesFailure'])
            .toMatchValues({ timeseriesDisplayState: 'error' })
    })

    it('surfaces per-day errors for a failed calculation', async () => {
        useMocks({
            get: {
                [TIMESERIES_URL]: () => [
                    200,
                    { status: 'failed', timeseries: { '2026-01-01': null }, errors: { '2026-01-01': 'boom' } },
                ],
            },
        })
        logic = experimentTimeseriesLogic({ experiment: EXPERIMENT, metric: METRIC })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadTimeseriesSuccess'])
            .toMatchValues({ timeseriesErrors: { '2026-01-01': 'boom' } })
    })
})
