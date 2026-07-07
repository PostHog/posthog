import { hexToRGBA, toOpaqueHex } from 'lib/utils/colors'

describe('colors utils', () => {
    describe('hexToRGBA()', () => {
        it('converts hex to RGBA correctly', () => {
            expect(hexToRGBA('#ff0000', 0.3)).toEqual('rgba(255,0,0,0.3)')
            expect(hexToRGBA('#0000Cc', 0)).toEqual('rgba(0,0,204,0)')
            expect(hexToRGBA('#5375ff', 1)).toEqual('rgba(83,117,255,1)')
        })
    })

    describe('toOpaqueHex()', () => {
        it.each([
            ['rgba(29,74,255,0.5)', '#1d4aff'],
            ['rgba(29, 74, 255, 0.5)', '#1d4aff'],
            ['rgb(29,74,255)', '#1d4aff'],
            ['rgba(0,0,0,0.5)', '#000000'],
            ['#1d4aff80', '#1d4aff'],
            ['#1d4aff', '#1d4aff'],
            ['var(--data-color-1)', 'var(--data-color-1)'],
        ])('strips alpha from %s -> %s', (input, expected) => {
            expect(toOpaqueHex(input)).toEqual(expected)
        })
    })
})
