import { maybeAddPreheaderToEmail } from './preheader'

describe('email preheader benchmark', () => {
    const CEILING_MS = 2500

    it.each([
        {
            shape: 'hidden tags that never close',
            html: `<body>${'<div style="display:none">'.repeat(64_000)}</body>`,
            prefix: '<body><span style="display:none',
        },
        {
            shape: 'comments that never close',
            html: `<body>${'<!--'.repeat(256_000)}</body>`,
            prefix: '<body><span style="display:none',
        },
        {
            shape: 'body tags that never end',
            html: '<body '.repeat(64_000),
            prefix: '<span style="display:none',
        },
    ] as const)('scans a body full of $shape under the ceiling', ({ html, prefix }) => {
        const started = performance.now()
        const out = maybeAddPreheaderToEmail(html, 'Preview')
        const elapsedMs = performance.now() - started

        expect(out.startsWith(prefix)).toBe(true)
        expect(elapsedMs).toBeLessThan(CEILING_MS)
    })
})
