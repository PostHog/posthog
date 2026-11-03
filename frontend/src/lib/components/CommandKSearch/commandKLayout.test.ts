import { convertKeyboardLayout } from './commandKLayout'

describe('convertKeyboardLayout', () => {
    test.each([
        ['фзш', 'api'],
        ['ашдеук', 'filter'],
        ['שפן', 'api'],
        ['شحه', 'api'],
        ['вфеф сфефдщп', 'data catalog'],
        ['api', null],
        ['фзш api', null],
        ['123', null],
    ])('converts %s to %s', (text, expected) => {
        expect(convertKeyboardLayout(text)).toBe(expected)
    })
})
