import type { ContentWidget, ContentWidgetParts } from '../dashboard/dashboardTypes'
import { showsPart } from './tileParts'

describe('showsPart', () => {
    test.each<{ name: string; parts: ContentWidget['parts']; part: keyof ContentWidgetParts; expected: boolean }>([
        { name: 'shows every part when parts is missing', parts: undefined, part: 'footer', expected: true },
        { name: 'hides a part set to false', parts: { footer: false }, part: 'footer', expected: false },
    ])('$name', ({ parts, part, expected }) => {
        expect(showsPart({ type: 'markdown', parts, config: { text: '' } }, part)).toBe(expected)
    })
})
