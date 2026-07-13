import { mathjax } from '@mathjax/src/mjs/mathjax.js'

import { renderLatexToNode } from './NotebookNodeLatex'

// Builds the retry signal MathJax throws (via retryAfter) when a glyph needs a dynamic font file:
// an error carrying a `retry` promise that settles once the load finishes (or fails).
const retrySignal = (retry: Promise<unknown>): Error => Object.assign(new Error('MathJax retry'), { retry })

describe('renderLatexToNode', () => {
    afterEach(() => {
        ;(mathjax as any).__resetConvert()
    })

    it('resolves with the rendered node when no dynamic font load is needed', async () => {
        const node = document.createElement('span')
        ;(mathjax as any).__setConvert(() => node)

        await expect(renderLatexToNode('E = mc^2')).resolves.toBe(node)
    })

    it('retries and resolves once the dynamic font file loads', async () => {
        const node = document.createElement('span')
        const convert = jest
            .fn()
            // First call: glyph needs the 'shapes' dynamic file, so convert throws a retry signal.
            .mockImplementationOnce(() => {
                throw retrySignal(Promise.resolve())
            })
            // Second call (after the load settles): rendering succeeds.
            .mockImplementationOnce(() => node)
        ;(mathjax as any).__setConvert(convert)

        await expect(renderLatexToNode('\\bigstar')).resolves.toBe(node)
        expect(convert).toHaveBeenCalledTimes(2)
    })

    it('rejects when a dynamic font file fails to load', async () => {
        ;(mathjax as any).__setConvert(() => {
            throw retrySignal(Promise.reject(new Error("dynamic file 'shapes' failed to load")))
        })

        await expect(renderLatexToNode('\\bigstar')).rejects.toThrow("dynamic file 'shapes' failed to load")
    })
})
