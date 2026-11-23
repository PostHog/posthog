import { defaultConfig } from '~/common/config/config'

import { addTrackingToEmail } from './email-tracking.service'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('email link tracking benchmark', () => {
    const CEILING_MS = 2500
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)
    const invocation = { functionId: 'fn-1', id: 'inv-1', teamId: 1, state: {} } as any
    const spaces = ' '.repeat(64_000)
    const pixelEnd = /^<img src="[^"]+" style="display: none;" \/><\/body>$/

    it.each([
        {
            shape: 'anchors that never close',
            mode: 'redirect',
            end: pixelEnd,
            body: '<a href="https://example.com/x">'.repeat(64_000),
            tagged: '<a href="https://example.com/x">'.repeat(64_000),
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
    ] as const)('tags a body full of $shape under the ceiling', ({ mode, body, tagged, end }) => {
        const started = performance.now()
        const out = addTrackingToEmail(`<body>${body}</body>`, invocation, signer, false, mode)
        const elapsedMs = performance.now() - started

        expect(out.startsWith(`<body>${tagged}`)).toBe(true)
        expect(out.slice(`<body>${tagged}`.length)).toMatch(end)
        expect(elapsedMs).toBeLessThan(CEILING_MS)
    })
})
