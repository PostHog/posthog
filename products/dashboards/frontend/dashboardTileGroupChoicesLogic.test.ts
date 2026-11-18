import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'
import type { AppContext } from '~/types'

import { dashboardTileGroupChoicesLogic } from './dashboardTileGroupChoicesLogic'

describe('dashboardTileGroupChoicesLogic', () => {
    const mountAs = (uuid: string): typeof dashboardTileGroupChoicesLogic => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            current_user: { ...MOCK_DEFAULT_USER, uuid },
        } as AppContext
        initKeaTests(false)
        dashboardTileGroupChoicesLogic.mount()
        return dashboardTileGroupChoicesLogic
    }

    beforeEach(() => {
        localStorage.clear()
    })

    it('keeps the choices of each viewer apart in a shared browser', () => {
        mountAs('viewer-a').actions.setTileGroupCollapsed(1, 'plans', true)

        expect(mountAs('viewer-b').values.tileGroupChoices).toEqual({})
        expect(mountAs('viewer-a').values.tileGroupChoices).toEqual({ 1: { plans: true } })
    })
})
