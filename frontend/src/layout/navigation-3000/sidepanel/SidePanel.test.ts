import { clampSidePanelWidth } from './SidePanel'

describe('clampSidePanelWidth', () => {
    // Regression guard: clamping against the whole window (the old behavior) let a dragged panel
    // consume the viewport and crush the scene into a sliver. The clamp must reserve scene width.
    it.each([
        // [description, rawWidth, windowWidth, expected]
        ['reserves scene width when the panel is dragged past the cap', 5309, 1920, 1280],
        ['leaves a panel narrower than the cap untouched', 512, 1920, 512],
        ['keeps the panel floor on a window too narrow to reserve the scene', 5309, 800, 330],
        ['caps a panel that would otherwise leave the scene a sliver', 900, 1000, 360],
        ['returns the raw width before the first client render', 5309, undefined, 5309],
    ])('%s', (_description, rawWidth, windowWidth, expected) => {
        expect(clampSidePanelWidth(rawWidth, windowWidth)).toBe(expected)
    })
})
