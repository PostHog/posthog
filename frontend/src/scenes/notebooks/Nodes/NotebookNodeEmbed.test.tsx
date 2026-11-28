import { getEmbedSandbox } from './NotebookNodeEmbed'

describe('getEmbedSandbox', () => {
    it.each([
        'https://www.youtube.com/embed/abc123',
        'https://youtube.com/embed/abc123',
        'https://www.youtube-nocookie.com/embed/abc123',
    ])('allows same-origin for the trusted video host %s', (url) => {
        expect(getEmbedSandbox(new URL(url))).toEqual('allow-scripts allow-popups allow-forms allow-same-origin')
    })

    it.each([
        'https://example.com/page',
        'https://notyoutube.com/embed/abc123',
        'https://youtube.com.example.com/embed/abc123',
        'http://www.youtube.com/embed/abc123',
    ])('keeps the strict sandbox for %s', (url) => {
        expect(getEmbedSandbox(new URL(url))).toEqual('allow-scripts allow-popups allow-forms')
    })
})
