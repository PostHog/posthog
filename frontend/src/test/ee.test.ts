export const ifEeIt = process.env.TEST_SEGMENT !== 'FOSS' ? it : it.skip
export const ifFossIt = process.env.TEST_SEGMENT !== 'EE' ? it : it.skip

import posthogEE from '@posthog/ee/exports'

describe('ee importing', () => {
    ifEeIt('should import actual ee code', () => {
        expect(posthogEE.enabled).toBe(true)
    })

    ifFossIt('should import actual ee code', () => {
        expect(posthogEE.enabled).toBe(false)
    })
})
