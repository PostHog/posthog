import { maybeAddPreheaderToEmail } from './preheader'

describe('email preheader benchmark', () => {
    const CEILING_MS = 2500

    it.each([
        { shape: 'hidden tags that never close', body: '<div style="display:none">'.repeat(64_000) },
        { shape: 'comments that never close', body: '<!--'.repeat(256_000) },
    ] as const)('scans a body full of $shape under the ceiling', ({ body }) => {
        const started = performance.now()
        const out = maybeAddPreheaderToEmail(`<body>${body}</body>`, 'Preview')
        const elapsedMs = performance.now() - started

        expect(out.startsWith('<body><span style="display:none')).toBe(true)
        expect(elapsedMs).toBeLessThan(CEILING_MS)
    })
})
