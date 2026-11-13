import { getDefaultRecordingApiBlocksConfig, parsePublicBlockLimits, parseReplayBlockRateLimits } from './types'

describe('parseReplayBlockRateLimits', () => {
    it('reads the default limits for every tier', () => {
        const limits = parseReplayBlockRateLimits(getDefaultRecordingApiBlocksConfig().RECORDING_API_BLOCK_RATE_LIMITS)

        expect(limits.free).toEqual({ bucketSize: 240, refillPerSecond: 1200 / 3600 })
        expect(Object.keys(limits).sort()).toEqual(['browser', 'enterprise', 'free', 'paid'])
    })

    it.each([
        ['a missing tier', '{"browser":[1,1],"free":[1,1],"paid":[1,1]}'],
        ['a non-positive size', '{"browser":[0,1],"free":[1,1],"paid":[1,1],"enterprise":[1,1]}'],
        ['a malformed entry', '{"browser":[1],"free":[1,1],"paid":[1,1],"enterprise":[1,1]}'],
    ])('refuses %s', (_, raw) => {
        expect(() => parseReplayBlockRateLimits(raw)).toThrow(/RECORDING_API_BLOCK_RATE_LIMITS/)
    })
})

describe('parsePublicBlockLimits', () => {
    it.each([
        ['an unparsable', NaN],
        ['an infinite', Infinity],
        ['a zero', 0],
    ])('refuses %s byte budget, which would disable the check', (_, value) => {
        expect(() => parsePublicBlockLimits({ RECORDING_API_PUBLIC_BLOCK_BYTES_IN_FLIGHT: value })).toThrow(
            /RECORDING_API_PUBLIC_BLOCK_BYTES_IN_FLIGHT/
        )
    })
})
