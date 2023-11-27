import fs from 'fs'

const eeFolderExists = fs.existsSync('ee/frontend/exports.ts')
export const ifEeIt = eeFolderExists ? it : it.skip
export const ifFossIt = !eeFolderExists ? it : it.skip
export const ifEeDescribe = eeFolderExists ? describe : describe.skip
export const ifFossDescribe = !eeFolderExists ? describe : describe.skip

import { importPostHogEE } from '@posthog/ee/exports'

describe('ee importing', () => {
    ifEeIt('should import actual ee code', async () => {
        expect((await importPostHogEE()).enabled).toBe(true)
    })

    ifFossIt('should import actual ee code', async () => {
        expect((await importPostHogEE()).enabled).toBe(false)
    })
})
