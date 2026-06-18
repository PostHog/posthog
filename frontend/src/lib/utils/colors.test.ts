import { hexToRGBA } from 'lib/utils/colors'

describe('colors utils', () => {
    describe('hexToRGBA()', () => {
        it('converts hex to RGBA correctly', () => {
            expect(hexToRGBA('#ff0000', 0.3)).toEqual('rgba(255,0,0,0.3)')
            expect(hexToRGBA('#0000Cc', 0)).toEqual('rgba(0,0,204,0)')
            expect(hexToRGBA('#5375ff', 1)).toEqual('rgba(83,117,255,1)')
        })
    })
})
