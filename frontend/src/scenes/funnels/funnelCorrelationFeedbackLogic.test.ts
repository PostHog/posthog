import { expectLogic } from 'kea-test-utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import posthog from 'posthog-js'

import { useAvailableFeatures } from '~/mocks/features'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, InsightLogicProps, InsightType } from '~/types'

import { funnelCorrelationFeedbackLogic } from './funnelCorrelationFeedbackLogic'

describe('funnelCorrelationFeedbackLogic', () => {
    let logic: ReturnType<typeof funnelCorrelationFeedbackLogic.build>

    beforeEach(() => {
        useAvailableFeatures([AvailableFeature.CORRELATION_ANALYSIS])
        initKeaTests(false)
    })

    const defaultProps: InsightLogicProps = {
        dashboardItemId: undefined,
        cachedInsight: {
            short_id: undefined,
            filters: {
                insight: InsightType.FUNNELS,
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 1 },
                ],
            },
            result: [],
        },
    }

    beforeEach(async () => {
        logic = funnelCorrelationFeedbackLogic(defaultProps)
        logic.mount()
    })

    it('opens detailed feedback on selecting a valid rating', async () => {
        await expectLogic(logic, () => {
            logic.actions.setCorrelationFeedbackRating(1)
        })
            .toMatchValues(logic, {
                correlationFeedbackRating: 1,
            })
            .toDispatchActions(logic, [
                (action) =>
                    action.type === logic.actionTypes.setCorrelationDetailedFeedbackVisible &&
                    action.payload.visible === true,
            ])
            .toMatchValues(logic, {
                correlationDetailedFeedbackVisible: true,
            })
    })

    it('doesnt opens detailed feedback on selecting an invalid rating', async () => {
        await expectLogic(logic, () => {
            logic.actions.setCorrelationFeedbackRating(0)
        })
            .toMatchValues(logic, {
                correlationFeedbackRating: 0,
            })
            .toDispatchActions(logic, [
                (action) =>
                    action.type === logic.actionTypes.setCorrelationDetailedFeedbackVisible &&
                    action.payload.visible === false,
            ])
            .toMatchValues(logic, {
                correlationDetailedFeedbackVisible: false,
            })
    })

    it('captures emoji feedback properly', async () => {
        jest.spyOn(posthog, 'capture')
        await expectLogic(logic, () => {
            logic.actions.setCorrelationFeedbackRating(1)
        })
            .toMatchValues(logic, {
                // reset after sending feedback
                correlationFeedbackRating: 1,
            })
            .toDispatchActions(eventUsageLogic, ['reportCorrelationAnalysisFeedback'])

        expect(posthog.capture).toBeCalledWith('correlation analysis feedback', { rating: 1 })
    })

    it('goes away on sending feedback, capturing it properly', async () => {
        jest.spyOn(posthog, 'capture')
        await expectLogic(logic, () => {
            logic.actions.setCorrelationFeedbackRating(2)
            logic.actions.setCorrelationDetailedFeedback('tests')
            logic.actions.sendCorrelationAnalysisFeedback()
        })
            .toMatchValues(logic, {
                // reset after sending feedback
                correlationFeedbackRating: 0,
                correlationDetailedFeedback: '',
                correlationFeedbackHidden: true,
            })
            .toDispatchActions(eventUsageLogic, ['reportCorrelationAnalysisDetailedFeedback'])
            .toFinishListeners()

        await expectLogic(eventUsageLogic).toFinishListeners()

        expect(posthog.capture).toBeCalledWith('correlation analysis feedback', { rating: 2 })
        expect(posthog.capture).toBeCalledWith('correlation analysis detailed feedback', {
            rating: 2,
            comments: 'tests',
        })
    })
})
