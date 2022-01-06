import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { urls } from 'scenes/urls'
import { initKeaTestLogic } from '~/test/init'
import { InsightType } from '~/types'
import { experimentLogic } from './experimentLogic'

jest.mock('lib/api')

describe('experimentLogic', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights`) {
            return { short_id: 'a5qqECqP', filters: { insight: InsightType.FUNNELS } }
        } else if (pathname === `api/projects/${MOCK_TEAM_ID}/experiments`) {
            return {
                count: 1,
                next: null,
                previous: null,
                results: [{ id: 1, name: 'Test Exp', description: 'bla' }],
            }
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: experimentLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    describe('when creating a new experiment', () => {
        it('creates an insight funnel and clears the new experiment form', async () => {
            router.actions.push(urls.experiment('new'))
            await expectLogic(logic).toDispatchActions(['setExperimentFunnelId']).toMatchValues({
                experimentFunnelId: 'a5qqECqP',
            })
        })
    })

    describe('selector values', () => {
        it('given an mde, calculates correct sample size', async () => {
            logic.actions.setNewExperimentData({ parameters: { minimum_sample_size: 1000 } })

            await expectLogic(logic).toMatchValues({
                minimumSampleSizePerVariant: 1000,
            })

            expect(logic.values.minimumDetectableChange(20)).toBeCloseTo(5.059)

            expect(logic.values.minimumDetectableChange(50)).toBeCloseTo(6.324)

            expect(logic.values.minimumDetectableChange(0)).toBeCloseTo(0)
        })

        it('given sample size and entrants, calculates correct running time', async () => {
            // 500 entrants over 14 days, 1000 sample size, so need twice the time
            expect(logic.values.expectedRunningTime(500, 1000)).toEqual(28)

            // 500 entrants over 14 days, 250 sample size, so need half the time
            expect(logic.values.expectedRunningTime(500, 250)).toEqual(7)

            // 0 entrants over 14 days, so infinite running time
            expect(logic.values.expectedRunningTime(0, 1000)).toEqual(Infinity)
        })
    })
})
