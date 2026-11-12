import { defaultConfig } from '~/common/config/config'

import { addTrackingToEmail } from './email-tracking.service'
import { EmailTrackingCodeSigner } from './helpers/tracking-code'

describe('email link tracking benchmark', () => {
    const CEILING_MS = 2500
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, defaultConfig.CDP_EMAIL_TRACKING_URL)
    const invocation = { functionId: 'fn-1', id: 'inv-1', teamId: 1, state: {} } as any
    const spaces = ' '.repeat(64_000)

    it.each([
        {
            shape: 'anchors that never close',
            mode: 'redirect',
            body: '<a href="https://example.com/x">'.repeat(64_000),
            tagged: '<a href="https://example.com/x">'.repeat(64_000),
        },
        {
            shape: 'anchor tags that never end',
            mode: 'redirect',
            body: '<a href="javascript:x" '.repeat(16_000),
            tagged: '<a href="javascript:x" '.repeat(16_000),
        },
        {
            shape: 'spaces inside an anchor tag',
            mode: 'ses',
            body: `<a href="https://example.com/x"${spaces}y>x</a>`,
            tagged: `<a href="https://example.com/x"${spaces}y ses:tags="phl:0">x</a>`,
        },
    ] as const)('tags a body full of $shape under the ceiling', ({ mode, body, tagged }) => {
        const started = performance.now()
        const out = addTrackingToEmail(`<body>${body}</body>`, invocation, signer, false, mode)
        const elapsedMs = performance.now() - started

        expect(out.startsWith(`<body>${tagged}<img src="`)).toBe(true)
        expect(out.endsWith('style="display: none;" /></body>')).toBe(true)
        expect(elapsedMs).toBeLessThan(CEILING_MS)
    })
})
