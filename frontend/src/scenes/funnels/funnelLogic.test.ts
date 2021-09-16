
let stime = new Date();
import { BuiltLogic } from 'kea'
// import api from 'lib/api'
import { mockAPICreate, mockAPIGet } from 'lib/api.mock'
// import * as utils from 'lib/utils'
import { initKeaTestLogic } from '~/test/utils'
import { funnelLogic } from './funnelLogic'
import { funnelLogicType } from './funnelLogicType'

jest.mock('posthog-js')
jest.mock('lib/api')
jest.mock('lib/utils')


describe('NPS Logic', () => {
    
    let logic: BuiltLogic<funnelLogicType>

    // mockAPICreate(async ({ url, data }) => {
    //     console.log(url, data)
    //     expect(1).toBe(2)
    //     expect(data).toMatchObject({"actions": [{"id": "$pageview", "order": 0}], "funnel_window_days": 14, "insight": "FUNNELS", "interval": "day"})
    //     return {'results': []}
    // })
    mockAPIGet(async ({pathname}) => {
        // Mock out api/insight call in funnelsModel.ts
        return {'results': [], 'next': null}
    })
    initKeaTestLogic({
        logic: funnelLogic,
        props: {
        },
        // waitFor: 'loadRemoteItemsSuccess',
        onLogic: (l) => (logic = l),
    })
    // console.log('three' + (new Date() - stime)/1000)

    it("Load results, don't send breakdown if old visualisation is shown", () => {
    // console.log('four' + (new Date() - stime)/1000)

        // utils.uuid = jest.fn()
        funnelLogic().actions.setFilters({
            'actions': [{'id': '$pageview', order: 0}, {'id': '$pageview', order: 0}],
            'breakdown': '$active_feature_flags'
        })
        funnelLogic().actions.loadResults(true)
    console.log('five' + (new Date() - stime)/1000)

        // expect(api.create.mock.calls[0][1]).toMatchObject(
        //     {"actions": [{"id": "$pageview", "order": 0}], "funnel_window_days": 14, "insight": "FUNNELS", "interval": "day"}
        // )
    })

})