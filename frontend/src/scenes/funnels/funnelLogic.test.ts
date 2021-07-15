import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import * as utils from 'lib/utils'
import { initKea } from '~/initKea'
import { funnelLogic } from './funnelLogic'

jest.mock('posthog-js')

describe('NPS Logic', () => {
    let unmount: () => void
    let unmountff: () => void
    let logic: () => void
    beforeEach(() => {
        initKea()
        unmount = funnelLogic.mount()
        unmountff = featureFlagLogic.mount()
    })
    afterEach(() => {
        unmount?.()
        unmountff?.()
    })

    test("Load results, don't send breakdown if old visualisation is shown", () => {
        api.create = jest.fn()
        utils.uuid = jest.fn()
        featureFlagLogic.actions.setFeatureFlags([])
        api.create.mockResolvedValue({
            result: [
                {'name': '$pageview', 'count': 2}
            ]
        })
        funnelLogic().actions.setFilters({
            'actions': [{'id': '$pageview', order: 0}],
            'breakdown': '$active_feature_flags'
        })
        funnelLogic().actions.loadResults()

        expect(api.create.mock.calls[0][0]).toBe("api/insight/funnel/?")
        expect(api.create.mock.calls[0][1]).toMatchObject(
            {"actions": [{"id": "$pageview", "order": 0}], "funnel_window_days": 14, "insight": "FUNNELS", "interval": "day"}
        )
    })

})