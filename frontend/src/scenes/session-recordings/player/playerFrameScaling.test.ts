import { getPlayerFrameScale } from 'scenes/session-recordings/player/playerFrameScaling'

describe('getPlayerFrameScale', () => {
    // A desktop capture (1710px wide) shown in a smaller player. Safari renders the
    // recording's mobile layout when the iframe is shrunk with `zoom`, because Safari
    // evaluates the iframe's media queries at the zoomed width. `transform` keeps the
    // iframe at its recorded width, so the media queries fire at the real viewport.
    it('scales a desktop recording with transform, never zoom, off iOS', () => {
        const result = getPlayerFrameScale({ width: 900, height: 500 }, { width: 1710, height: 881 }, false)

        expect(result.zoom).toBeNull()
        expect(result.transform).toBe(`scale(${result.scale})`)
        expect(result.scale).toBeLessThan(1)
    })

    it('scales with zoom on iOS to avoid the pinch-zoom crash', () => {
        const result = getPlayerFrameScale({ width: 900, height: 500 }, { width: 1710, height: 881 }, true)

        expect(result.transform).toBeNull()
        expect(result.zoom).toBe(String(result.scale))
    })

    it('drops the transform when no shrink is needed, so Chrome does not paint outside the clip', () => {
        const result = getPlayerFrameScale({ width: 1920, height: 1080 }, { width: 1710, height: 881 }, false)

        expect(result.scale).toBe(1)
        expect(result.transform).toBeNull()
        expect(result.zoom).toBeNull()
    })

    it('picks the smaller axis ratio so the recording fits both dimensions', () => {
        const result = getPlayerFrameScale({ width: 855, height: 881 }, { width: 1710, height: 881 }, false)

        expect(result.scale).toBe(0.5)
    })
})
