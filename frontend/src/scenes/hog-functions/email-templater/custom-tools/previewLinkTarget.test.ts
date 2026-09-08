import { previewLinkTargetCustomJs } from './previewLinkTarget'

describe('previewLinkTargetCustomJs', () => {
    // The customJS runs as a string inside Unlayer's iframe, so typecheck cannot see it. Run it
    // against a stub of the parts of the Unlayer API it touches.
    function runPreviewHtml(html?: string): string {
        let previewHtml: ((params: { html?: string }, done: (result: { html: string }) => void) => void) | undefined
        const unlayer = {
            registerCallback: (name: string, callback: typeof previewHtml): void => {
                if (name === 'previewHtml') {
                    previewHtml = callback
                }
            },
        }
        new Function('unlayer', previewLinkTargetCustomJs)(unlayer)
        if (!previewHtml) {
            throw new Error('previewHtml callback was not registered')
        }
        let result = ''
        previewHtml({ html }, (params) => {
            result = params.html
        })
        return result
    }

    it.each([
        [
            'a full document',
            '<!DOCTYPE html><html><head><title>t</title></head><body>hi</body></html>',
            '<!DOCTYPE html><html><head><base target="_blank"><title>t</title></head><body>hi</body></html>',
        ],
        ['markup with no head', '<div>hi</div>', '<base target="_blank"><div>hi</div>'],
        ['empty markup', undefined, '<base target="_blank">'],
    ])('gives %s a default link target', (_name, html, expected) => {
        expect(runPreviewHtml(html)).toEqual(expected)
    })
})
