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

    test.each([
        ['the Escape key', (): void => void window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
        ['the browser leaving full screen', (): void => void document.dispatchEvent(new Event('fullscreenchange'))],
    ])('leaves full screen on %s', (_, exit) => {
        const logic = canvasFullscreenLogic({ id: 'canvas-1' })
        logic.mount()

        logic.actions.setFullscreen(true)
        expect(logic.values.fullscreen).toBe(true)

        exit()
        expect(logic.values.fullscreen).toBe(false)

        logic.unmount()
    })
})
