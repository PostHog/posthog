import { type SavedPanel, type ContentPanelParts } from '../../panels/core/panelSchema'
import { showsPart } from './tileParts'

describe('showsPart', () => {
    test.each<{ name: string; parts: SavedPanel['parts']; part: keyof ContentPanelParts; expected: boolean }>([
        { name: 'shows every part when parts is missing', parts: undefined, part: 'footer', expected: true },
        { name: 'hides a part set to false', parts: { footer: false }, part: 'footer', expected: false },
    ])('$name', ({ parts, part, expected }) => {
        expect(showsPart({ type: 'markdown', parts, config: { text: '' } }, part)).toBe(expected)
    })
})
