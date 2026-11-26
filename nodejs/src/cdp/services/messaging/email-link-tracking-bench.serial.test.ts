import { defaultConfig } from '~/common/config/config'

import { addTrackingToEmail } from './email-tracking.service'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('email link tracking benchmark', () => {
    const CEILING_MS = 2500
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)
    const invocation = { functionId: 'fn-1', id: 'inv-1', teamId: 1, state: {} } as any
    const spaces = ' '.repeat(64_000)
    const pixelEnd = /^<img src="[^"]+" style="display: none;" \/><\/body>$/
    const redirected = addTrackingToEmail(
        '<a href="https://example.com/x">x</a>',
        invocation,
        signer,
        false,
        'redirect'
    ).match(/^<a href="[^"]+">/)![0]
    const indexed = (count: number, anchor: (index: number) => string): string =>
        Array.from({ length: count }, (_, index) => anchor(index)).join('')

    it.each([
        {
            shape: 'anchors that never close',
            mode: 'redirect',
            end: pixelEnd,
            body: '<a href="https://example.com/x">'.repeat(64_000),
            tagged: redirected.repeat(64_000),
        },
        {
            shape: 'anchor tags that never end',
            mode: 'redirect',
            end: pixelEnd,
            body: '<a href="javascript:x" '.repeat(16_000),
            tagged: '<a href="javascript:x" '.repeat(16_000),
        },
        {
            shape: 'spaces inside an anchor tag',
            mode: 'ses',
            end: /^<\/body>$/,
            body: `<a href="https://example.com/x"${spaces}y>x</a>`,
            tagged: `<a href="https://example.com/x"${spaces}y ses:tags="phl:0">x</a>`,
        },
        {
            shape: 'link openers inside a quoted value',
            mode: 'ses',
            end: /^<\/body>$/,
            body: `<a title="${'<a '.repeat(32_000)}">x</a>`,
            tagged: `<a title="${'<a '.repeat(32_000)}">x</a>`,
        },
        {
            shape: 'links after comments that never close',
            mode: 'ses',
            end: /^<\/body>$/,
            body: '<!--<a href="https://example.com/x" data-ph-no-track>x</a>'.repeat(32_000),
            tagged: '<!--<a href="https://example.com/x" data-ph-no-track ses:no-track>x</a>'.repeat(32_000),
        },
        {
            shape: 'links whose comments hold end tags',
            mode: 'ses',
            end: /^<\/body>$/,
            body: '<a href="https://example.com/x"><!--</a>-->'.repeat(32_000),
            tagged: indexed(32_000, (index) => `<a href="https://example.com/x" ses:tags="phl:${index}"><!--</a>-->`),
        },
        {
            shape: 'anchors that never close before a comment holding an end tag',
            mode: 'ses',
            end: /^<\/body>$/,
            body: `${'<a href="https://example.com/x">'.repeat(64_000)}<!--</a>-->`,
            tagged: `${indexed(64_000, (index) => `<a href="https://example.com/x" ses:tags="phl:${index}">`)}<!--</a>-->`,
        },
        {
            shape: 'tags with a quoted > before a quote that never closes',
            mode: 'ses',
            end: /^<\/body>$/,
            body: `${"<a b='>'".repeat(32_000)}<a c="`,
            tagged: `${"<a b='>'".repeat(32_000)}<a c="`,
        },
        {
            shape: 'SVG CDATA sections that never close',
            mode: 'ses',
            end: /^<\/body>$/,
            body: `<svg>${'<![CDATA[<a href="https://example.com/x" data-ph-no-track>x</a>'.repeat(32_000)}`,
            tagged: `<svg>${'<![CDATA[<a href="https://example.com/x" data-ph-no-track ses:no-track>x</a>'.repeat(32_000)}`,
        },
        {
            shape: 'style blocks that never close',
            mode: 'ses',
            end: /^<\/body>$/,
            body: '<style><a href="https://example.com/x" data-ph-no-track>x</a>'.repeat(32_000),
            tagged: '<style><a href="https://example.com/x" data-ph-no-track ses:no-track>x</a>'.repeat(32_000),
        },
    ] as const)('tags a body full of $shape under the ceiling', ({ mode, body, tagged, end }) => {
        const started = performance.now()
        const out = addTrackingToEmail(`<body>${body}</body>`, invocation, signer, false, mode)
        const elapsedMs = performance.now() - started

        expect(out.startsWith(`<body>${tagged}`)).toBe(true)
        expect(out.slice(`<body>${tagged}`.length)).toMatch(end)
        expect(elapsedMs).toBeLessThan(CEILING_MS)
    })
})
