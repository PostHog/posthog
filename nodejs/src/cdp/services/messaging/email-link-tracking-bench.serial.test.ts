import { defaultConfig } from '~/common/config/config'

import { EmailTrackingMode, addTrackingToEmail } from './email-tracking.service'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('email link tracking benchmark', () => {
    const CEILING_MS = 2500
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)
    const invocation = { functionId: 'fn-1', id: 'inv-1', teamId: 1, state: {} } as any
    const spaces = ' '.repeat(64_000)

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
