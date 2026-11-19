import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'
import { DashboardType } from '~/types'

import { buttonTileCardModalLogic } from './buttonTileCardModalLogic'

describe('buttonTileCardModalLogic', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('calls the close handler after saving a new button', () => {
        const onClose = jest.fn()
        const logic = buttonTileCardModalLogic({
            dashboard: { id: 5, tiles: [] } as unknown as DashboardType,
            buttonTileId: null,
            onClose,
        })
        logic.mount()

        logic.actions.submitButtonTileSuccess({
            url: '/example',
            text: 'Example',
            placement: 'left',
            style: 'primary',
            transparent_background: false,
        })

        expect(onClose).toHaveBeenCalledTimes(1)
        expect(posthog.capture).toHaveBeenCalledWith(
            'dashboard button tile saved',
            expect.objectContaining({ dashboard_id: 5, is_new: true })
        )
    })
})
