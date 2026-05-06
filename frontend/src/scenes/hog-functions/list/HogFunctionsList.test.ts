import { HogFunctionType } from '~/types'

import { urlForHogFunction } from './HogFunctionsList'

const makeFn = (id: string): HogFunctionType => ({ id }) as HogFunctionType

describe('urlForHogFunction', () => {
    it('returns the bare hog function path when returnTo is undefined', () => {
        expect(urlForHogFunction(makeFn('abc123'))).toBe('/functions/abc123')
    })

    it('appends returnTo as a query param for a hog function id', () => {
        expect(urlForHogFunction(makeFn('abc123'), '/health/sdk-doctor')).toBe(
            '/functions/abc123?returnTo=%2Fhealth%2Fsdk-doctor'
        )
    })

    it('does not append returnTo for plugin- prefix IDs', () => {
        expect(urlForHogFunction(makeFn('plugin-7'), '/health/sdk-doctor')).toBe('/pipeline/plugins/7')
    })

    it('does not append returnTo for batch-export- prefix IDs', () => {
        expect(urlForHogFunction(makeFn('batch-export-9'), '/health/sdk-doctor')).toBe('/pipeline/batch-exports/9')
    })
})
