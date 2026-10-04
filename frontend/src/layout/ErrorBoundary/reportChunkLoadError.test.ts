import posthog from 'posthog-js'

import { reportChunkLoadError } from './reportChunkLoadError'

describe('reportChunkLoadError', () => {
    // A panel that remounts while it streams threw the same dead import dozens of times a second,
    // and every throw reached error tracking as its own exception.
    it('reports a repeating chunk-load failure once per page load', () => {
        const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(jest.fn())
        const error = new TypeError('Failed to fetch dynamically imported module: /static/QueryWidget.js')

        for (let attempt = 0; attempt < 5; attempt++) {
            reportChunkLoadError(error, 2)
        }

        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(captureSpy).toHaveBeenCalledWith(error, { chunk_load_error: true, team_id: 2 })
        captureSpy.mockRestore()
    })
})
