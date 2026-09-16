import { render } from '@testing-library/react'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { DashboardErrorTileItem } from './DashboardErrorTileItem'

describe('DashboardErrorTileItem', () => {
    it('identifies the failing tile in error telemetry', () => {
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')

        const tile = { id: 4321 } as DashboardTile<QueryBasedInsightModel>
        render(<DashboardErrorTileItem tile={tile} dashboardId={99} />)

        const shownCalls = captureSpy.mock.calls.filter((call) => call[0] === 'insight error message shown')
        expect(shownCalls).toHaveLength(1)
        expect(shownCalls[0][1]).toMatchObject({ dashboard_id: 99, tile_id: 4321 })
    })
})
