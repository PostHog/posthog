import fs from 'fs'

const eeFolderExists = fs.existsSync('ee/frontend/exports.ts')
export const ifEeIt = eeFolderExists ? it : it.skip
export const ifFossIt = !eeFolderExists ? it : it.skip

import posthogEE from '@posthog/ee/exports'

describe('ee importing', () => {
    ifEeIt('should import actual ee code', () => {
        expect(posthogEE.enabled).toBe(true)
    })

    ifFossIt('should import actual ee code', () => {
        expect(posthogEE.enabled).toBe(false)
    })
})
