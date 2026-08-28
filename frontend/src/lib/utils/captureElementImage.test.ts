import { toBlob } from 'html-to-image'

import { captureElementImage } from './captureElementImage'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))

describe('captureElementImage', () => {
    it('leaves CSS custom properties out of the copied style properties', async () => {
        document.documentElement.style.setProperty('--a-design-token', 'red')

        await captureElementImage(document.createElement('div'))

        const { includeStyleProperties } = (toBlob as jest.Mock).mock.calls[0][1]
        expect(includeStyleProperties).not.toBeUndefined()
        expect(includeStyleProperties.filter((name: string) => name.startsWith('--'))).toEqual([])
    })
})
