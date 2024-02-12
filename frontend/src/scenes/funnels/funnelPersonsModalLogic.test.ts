import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { openPersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightShortId, InsightType } from '~/types'

import { funnelPersonsModalLogic } from './funnelPersonsModalLogic'

jest.mock('scenes/trends/persons-modal/PersonsModal')

const Insight123 = '123' as InsightShortId

describe('funnelPersonsModalLogic', () => {
    let logic: ReturnType<typeof funnelPersonsModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/': {
                    results: [{}],
                },
            },
        })
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
            result: null,
        },
    }

    async function initFunnelPersonsModalLogic(props: InsightLogicProps = defaultProps): Promise<void> {
        teamLogic.mount()
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = funnelPersonsModalLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    describe('it opens the PersonsModal', () => {
        const props = { dashboardItemId: Insight123 }
        beforeEach(async () => {
            await initFunnelPersonsModalLogic(props)
        })

        test('openPersonsModalForStep calls openPersonsModal', async () => {
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            logic.actions.openPersonsModalForStep({
                step: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                },
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith({
                title: expect.any(Object),
                url: '/some/people/url?funnel_step=2', // Positive funnel_step and no funnel_step_breakdown
            })
        })

        test('openPersonsModalForSeries calls openPersonsModal', async () => {
            await expectLogic().toDispatchActions(preflightLogic, ['loadPreflightSuccess'])
            await expectLogic(() => {
                router.actions.push(urls.insightEdit(Insight123))
            })

            logic.actions.openPersonsModalForSeries({
                series: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=Latvia',
                    droppedOffFromPrevious: 0,
                    conversionRates: {
                        fromPrevious: 1,
                        total: 1,
                        fromBasisStep: 1,
                    },
                },
                step: {
                    action_id: '$pageview',
                    average_conversion_time: 0,
                    median_conversion_time: 0,
                    count: 1,
                    name: '$pageview',
                    order: 0,
                    type: 'events',
                    // Breakdown must be ignored in openPersonsModalForStep
                    converted_people_url: '/some/people/url?funnel_step=2&funnel_step_breakdown=USA',
                    dropped_people_url: '/some/people/url?funnel_step=-2&funnel_step_breakdown=USA',
                },
                converted: true,
            })

            expect(openPersonsModal).toHaveBeenCalledWith({
                title: expect.any(Object),
                url: '/some/people/url?funnel_step=2&funnel_step_breakdown=Latvia', // Series funnel_step_breakdown included
            })
        })
    })
})
