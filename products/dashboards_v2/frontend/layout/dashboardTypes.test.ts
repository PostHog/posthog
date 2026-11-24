import { type ContentWidget, type ContentWidgetParts, showsPart } from './dashboardTypes'

describe('showsPart', () => {
    test.each<{ name: string; parts: ContentWidget['parts']; part: keyof ContentWidgetParts; expected: boolean }>([
        { name: 'shows every part when parts is missing', parts: undefined, part: 'footer', expected: true },
        { name: 'hides a part set to false', parts: { footer: false }, part: 'footer', expected: false },
        {
            name: 'hides the description with the header',
            parts: { header: false },
            part: 'description',
            expected: false,
        },
        {
            name: 'hides the description with the header even when it is set to true',
            parts: { header: false, description: true },
            part: 'description',
            expected: false,
        },
    ])('$name', ({ parts, part, expected }) => {
        expect(showsPart({ type: 'markdown', parts }, part)).toBe(expected)
    })
})
