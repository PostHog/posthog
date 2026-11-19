import { defaultConfig } from '~/common/config/config'

import { EmailTrackingMode, addTrackingToEmail } from './email-tracking.service'
import { MIN_NESTING_LIMIT } from './helpers/href-anchors'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('email link tracking benchmark', () => {
    const CEILING_MS = 2500
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)
    const invocation = { functionId: 'fn-1', id: 'inv-1', teamId: 1, state: {} } as any
    const spaces = ' '.repeat(64_000)
    // Each end tag that matches no open element is looked for through all of them. The body holds enough tags that
    // the nesting limit is at its floor.
    const deepestNesting = '<span>'.repeat(MIN_NESTING_LIMIT - 3)
    const unmatchedEndTags = '</x>'.repeat(400_000)
    const attributes = Array.from({ length: 150_000 }, (_, i) => `a${i}`).join(' ')
    const textBeforeTable = 'x<b></b>'.repeat(200_000)
    const longTag = `<a href="https://example.com/x" ${Array.from({ length: 2_000 }, (_, i) => `a${i}`).join(' ')}>`
    const rebuiltLinks = '<p>x</p>'.repeat(20_000)
    const blockChildren = '<br>'.repeat(400_000)
    const repeatedBodyTags = Array.from({ length: 40_000 }, (_, i) => `<body a${i}>`).join('')

    it.each<{ shape: string; mode: EmailTrackingMode; body: string; tagged: string; pixel?: boolean }>([
        {
            shape: 'anchors that never close',
            mode: 'ses',
            body: '<a href="https://example.com/x">'.repeat(64_000),
            tagged: Array.from(
                { length: 64_000 },
                (_, i) => `<a href="https://example.com/x" ses:tags="phl:${i}">`
            ).join(''),
        },
        {
            shape: 'comments opened inside a comment',
            mode: 'ses',
            body: `<!--${'<!--<a href="https://example.com/x">'.repeat(16_000)}-->`,
            tagged: `<!--${Array.from({ length: 16_000 }, (_, i) => `<!--<a href="https://example.com/x" ses:tags="phl:${i}">`).join('')}-->`,
        },
        {
            shape: 'style elements between links',
            mode: 'ses',
            body: '<style>p{}</style/><a href="https://example.com/x">'.repeat(16_000),
            tagged: Array.from(
                { length: 16_000 },
                (_, i) => `<style>p{}</style/><a href="https://example.com/x" ses:tags="phl:${i}">`
            ).join(''),
        },
        {
            shape: 'anchor tags that never end',
            mode: 'redirect',
            // The tag never ends, so its `</body>` is not an end tag and the email gets no pixel.
            body: '<a href="javascript:x" '.repeat(16_000),
            tagged: '<a href="javascript:x" '.repeat(16_000),
            pixel: false,
        },
        {
            shape: 'end tags under the deepest nesting read',
            mode: 'ses',
            body: `${deepestNesting}${unmatchedEndTags}<a href="https://example.com/x">x</a>`,
            tagged: `${deepestNesting}${unmatchedEndTags}<a href="https://example.com/x" ses:tags="phl:0">x</a>`,
        },
        {
            shape: 'attributes in one anchor tag',
            mode: 'ses',
            body: `<a href="https://example.com/x" ${attributes}>x</a>`,
            tagged: `<a href="https://example.com/x" ${attributes} ses:tags="phl:0">x</a>`,
        },
        {
            shape: 'text and tags placed before an open table',
            mode: 'ses',
            body: `<table>${textBeforeTable}<a href="https://example.com/x">x</a>`,
            tagged: `<table>${textBeforeTable}<a href="https://example.com/x" ses:tags="phl:0">x</a>`,
        },
        {
            shape: 'copies of a long anchor tag that misnested end tags rebuild',
            mode: 'ses',
            body: `<p>${longTag}x</p>${rebuiltLinks}`,
            tagged: `<p>${longTag.slice(0, -1)} ses:tags="phl:0">x</p>${rebuiltLinks}`,
        },
        {
            shape: 'children of a block that a misnested anchor end tag moves',
            mode: 'ses',
            body: `<a href="https://example.com/x"><div>${blockChildren}</a>`,
            tagged: `<a href="https://example.com/x" ses:tags="phl:0"><div>${blockChildren}</a>`,
        },
        {
            shape: 'body start tags with new attributes',
            mode: 'ses',
            body: `${repeatedBodyTags}<a href="https://example.com/x">x</a>`,
            tagged: `${repeatedBodyTags}<a href="https://example.com/x" ses:tags="phl:0">x</a>`,
        },
        {
            shape: 'spaces inside an anchor tag',
            mode: 'ses',
            body: `<a href="https://example.com/x"${spaces}y>x</a>`,
            tagged: `<a href="https://example.com/x"${spaces}y ses:tags="phl:0">x</a>`,
        },
    ])('tags a body full of $shape under the ceiling', ({ mode, body, tagged, pixel = true }) => {
        const started = performance.now()
        const out = addTrackingToEmail(`<body>${body}</body>`, invocation, signer, false, mode)
        const elapsedMs = performance.now() - started

        if (pixel) {
            expect(out.startsWith(`<body>${tagged}<img src="`)).toBe(true)
            expect(out.endsWith('style="display: none;" /></body>')).toBe(true)
        } else {
            expect(out).toBe(`<body>${tagged}</body>`)
        }
        expect(elapsedMs).toBeLessThan(CEILING_MS)
    })
})
