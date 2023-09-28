import { maxDefined, minDefined } from '../../../../src/main/ingestion-queues/session-recording/utils'

describe('session-recording utils', () => {
    it('minDefined', () => {
        expect(minDefined(1, 2, 3)).toEqual(1)
        expect(minDefined(1, undefined, 3)).toEqual(1)
        expect(minDefined(undefined, undefined, undefined)).toEqual(undefined)
        expect(maxDefined()).toEqual(undefined)
    })

    it('maxDefined', () => {
        expect(maxDefined(1, 2, 3)).toEqual(3)
        expect(maxDefined(1, undefined, 3)).toEqual(3)
        expect(maxDefined(undefined, undefined, undefined)).toEqual(undefined)
        expect(maxDefined()).toEqual(undefined)
    })
})
