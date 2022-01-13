import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { urls } from 'scenes/urls'
import { initKeaTestLogic } from '~/test/init'
import { InsightType } from '~/types'
import { experimentLogic } from './experimentLogic'

jest.mock('lib/api')

describe('experimentLogic', () => {
    let logic: ReturnType<typeof experimentLogic.build>

    mockAPI(async ({ pathname }) => {
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
    })

    initKeaTestLogic({
        logic: experimentLogic,
        props: {},
        onLogic: (l) => (logic = l),
    })

    describe('when creating a new experiment', () => {
        it('creates an insight funnel and clears the new experiment form', async () => {
            router.actions.push(urls.experiment('new'))
            await expectLogic(logic).toDispatchActions(['setExperimentInsightId']).toMatchValues({
                experimentInsightId: 'a5qqECqP',
            })
        })
    })

    describe('selector values', () => {
        it('given a sample size and conversion rate, calculates correct mde', async () => {
            expect(logic.values.mdeGivenSampleSizeAndConversionRate(1000, 20)).toBeCloseTo(5.059)
            expect(logic.values.mdeGivenSampleSizeAndConversionRate(100, 20)).toBeCloseTo(16)

            expect(logic.values.mdeGivenSampleSizeAndConversionRate(1000, 50)).toBeCloseTo(6.324)
            expect(logic.values.mdeGivenSampleSizeAndConversionRate(100, 50)).toBeCloseTo(20)

            expect(logic.values.mdeGivenSampleSizeAndConversionRate(1000, 0)).toBeCloseTo(0)
            expect(logic.values.mdeGivenSampleSizeAndConversionRate(100, 0)).toBeCloseTo(0)
        })

        it('given an mde, calculates correct sample size', async () => {
            logic.actions.setNewExperimentData({ parameters: { minimum_detectable_effect: 10 } })

            await expectLogic(logic).toMatchValues({
                minimumDetectableChange: 10,
            })

            expect(logic.values.minimumSampleSizePerVariant(20)).toEqual(256)

            expect(logic.values.minimumSampleSizePerVariant(40)).toEqual(384)

            expect(logic.values.minimumSampleSizePerVariant(0)).toEqual(0)
        })

        it('given count data and exposure, calculates correct mde', async () => {
            expect(logic.values.mdeGivenCountData(5000)).toEqual(201)
            expect(logic.values.mdeGivenCountData(500)).toEqual(64)

            expect(logic.values.mdeGivenCountData(1000000)).toEqual(2829)
            expect(logic.values.mdeGivenCountData(10000)).toEqual(283)
            expect(logic.values.mdeGivenCountData(1000)).toEqual(90)
            expect(logic.values.mdeGivenCountData(100)).toEqual(29)
            expect(logic.values.mdeGivenCountData(10)).toEqual(9)
            expect(logic.values.mdeGivenCountData(1)).toEqual(3)
        })

        it('given sample size and entrants, calculates correct running time', async () => {
            // 500 entrants over 14 days, 1000 sample size, so need twice the time
            expect(logic.values.expectedRunningTime(500, 1000)).toEqual(28)

            // 500 entrants over 14 days, 250 sample size, so need half the time
            expect(logic.values.expectedRunningTime(500, 250)).toEqual(7)

            // 0 entrants over 14 days, so infinite running time
            expect(logic.values.expectedRunningTime(0, 1000)).toEqual(Infinity)
        })

        it('given control count data, calculates correct running time', async () => {
            // 1000 count over 14 days
            expect(logic.values.recommendedExposureForCountData(1000)).toEqual(91.8)

            // 10,000 entrants over 14 days
            // 10x entrants, so 1/10th running time
            expect(logic.values.recommendedExposureForCountData(10000)).toEqual(9.2)

            // 0 entrants over 14 days, so infinite running time
            expect(logic.values.recommendedExposureForCountData(0)).toEqual(Infinity)
        })
    })
})
