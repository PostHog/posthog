import { toBlob } from 'html-to-image'

import { captureElementAsPng } from './copyImageToClipboard'

jest.mock('html-to-image', () => ({
    toBlob: jest.fn(() => Promise.resolve(new Blob(['png'], { type: 'image/png' }))),
}))

describe('captureElementAsPng', () => {
    async function filterFor(excludeSelector?: string): Promise<((node: Node) => boolean) | undefined> {
        await captureElementAsPng(document.createElement('div'), excludeSelector)
        return (toBlob as jest.Mock).mock.calls[0][1].filter
    }

    it('keeps everything when nothing is excluded', async () => {
        expect(await filterFor()).toBeUndefined()
    })

    it('draws the element at the origin, so a grid tile is not translated out of its own image', async () => {
        await captureElementAsPng(document.createElement('div'))
        const { style } = (toBlob as jest.Mock).mock.calls[0][1]

        expect(style).toEqual({ transform: 'none', position: 'relative', inset: 'auto', margin: '0' })
    })

    it('drops the excluded elements and keeps the rest', async () => {
        document.body.innerHTML = '<div class="CardMeta__controls">⋯</div><div class="chart">chart</div>'
        const filter = await filterFor('.CardMeta__controls')

        expect(filter!(document.querySelector('.CardMeta__controls')!)).toBe(false)
        expect(filter!(document.querySelector('.chart')!)).toBe(true)
        expect(filter!(document.createTextNode('a label'))).toBe(true)
    })
})
