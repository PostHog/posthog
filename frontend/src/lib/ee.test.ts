import fs from 'fs'

import posthogEE from '@posthog/ee/exports'

import { PostHogEE } from '../../@posthog/ee/types'

const eeFolderExists = fs.existsSync('../ee/frontend/exports.ts')
export const ifEeIt = eeFolderExists ? it : it.skip
export const ifFossIt = !eeFolderExists ? it : it.skip
export const ifEeDescribe = eeFolderExists ? describe : describe.skip
export const ifFossDescribe = !eeFolderExists ? describe : describe.skip

describe('ee importing', () => {
    let posthogEEModule: PostHogEE

    beforeEach(async () => {
        posthogEEModule = await posthogEE()
    })
    ifEeIt('should import actual ee code', () => {
        expect(posthogEEModule.enabled).toBe(true)
    })

    ifFossIt('should import actual ee code', () => {
        expect(posthogEEModule.enabled).toBe(false)
    })
})
