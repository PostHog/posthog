import { HogFunctionType } from '~/types'

import { urlForHogFunction } from './HogFunctionsList'

const makeFn = (id: string): HogFunctionType => ({ id }) as HogFunctionType

describe('urlForHogFunction', () => {
    it('returns the bare hog function path when returnTo is undefined', () => {
        expect(urlForHogFunction(makeFn('abc123'))).toBe('/functions/abc123')
    })

    it('appends returnTo as a query param for a hog function id', () => {
        expect(urlForHogFunction(makeFn('abc123'), '/health/sdk-health')).toBe(
            '/functions/abc123?returnTo=%2Fhealth%2Fsdk-health'
        )
    })

    it('does not append returnTo for plugin- prefix IDs', () => {
        expect(urlForHogFunction(makeFn('plugin-7'), '/health/sdk-health')).toBe('/pipeline/plugins/7')
    })
})
