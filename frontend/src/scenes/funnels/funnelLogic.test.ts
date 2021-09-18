import { BuiltLogic } from 'kea'
import { funnelLogic } from './funnelLogic'
import { funnelLogicType } from './funnelLogicType'
import { mockAPIGet } from 'lib/api.mock'
import { initKeaTestLogic, expectLogic } from '~/test/kea-test-utils'

jest.mock('lib/api')

describe('funnelLogic', () => {
    let logic: BuiltLogic<funnelLogicType>

    mockAPIGet(async ({ pathname }) => {
        if (pathname === 'api/insight/') {
            return { results: [], next: null }
        } else if (pathname === '_preflight/') {
            return {}
        } else {
            debugger
            throw new Error()
        }
    })

    initKeaTestLogic({
        logic: funnelLogic,
        props: {
            filters: {
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 0 },
                ],
                breakdown: '$active_feature_flags',
            },
        },
        onLogic: (l) => (logic = l),
    })

    it('loads preflight on load', async () => {
        await expectLogic(logic)
            .delay(3000)
            .printActions()
            .toDispatchActions([
                'load preflight (scenes.PreflightCheck.logic)',
                'load preflight success (scenes.PreflightCheck.logic)',
                'register instrumentation props (scenes.PreflightCheck.logic)',
            ])
    })

    it('loads all funnels on load', async () => {
        await expectLogic(logic)
            .delay(3000)
            .printActions()
            .toDispatchActions([
                'loadFunnels',

                'load funnels (models.funnelsModel)',
                'set next (models.funnelsModel)',
                'load funnels success (models.funnelsModel)',
            ])
    })

    it("Load results, don't send breakdown if old visualisation is shown", async () => {
        //
        //     // utils.uuid = jest.fn()
        // funnelLogic().actions.setFilters({
        //     actions: [
        //         { id: '$pageview', order: 0 },
        //         { id: '$pageview', order: 0 },
        //     ],
        //     breakdown: '$active_feature_flags',
        // })
        //     funnelLogic().actions.loadResults(true)
        // console.log('five' + (new Date() - stime)/1000)
        //
        //     // expect(api.create.mock.calls[0][1]).toMatchObject(
        //     //     {"actions": [{"id": "$pageview", "order": 0}], "funnel_window_days": 14, "insight": "FUNNELS", "interval": "day"}
        //     // )

        await expectLogic(logic, () => {
            logic.actions.setFilters({
                actions: [
                    { id: '$pageview', order: 0 },
                    { id: '$pageview', order: 0 },
                ],
                breakdown: '$active_feature_flags',
            })
        })
            .printActions()
            .toDispatchActions(['setFilters'])
            .toMatchValues({
                remoteItems: expect.objectContaining({
                    results: expect.arrayContaining([expect.objectContaining({ name: 'event1' })]),
                }),
            })
    })
})
