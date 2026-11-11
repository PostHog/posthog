import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { canvasFullscreenLogic } from './canvasFullscreenLogic'

describe('canvasFullscreenLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/:id/view/': [404, {}],
                '/api/projects/:team_id/canvases/:id/builds/': { builds: [], published_build_id: null },
            },
        })
        initKeaTests()
    })

    it('leaves full page on the Escape key', () => {
        const logic = canvasFullscreenLogic({ id: 'canvas-1' })
        logic.mount()

        logic.actions.setFullscreen(true)
        expect(logic.values.fullscreen).toBe(true)

        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
        expect(logic.values.fullscreen).toBe(false)

        logic.unmount()
    })
})
