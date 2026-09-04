import { resolveHighVolumeOffender } from './IngestionWarningsView'

describe('resolveHighVolumeOffender', () => {
    // The regression this guards: a multi-key batch carries no real distinctId, so the consumer
    // backfills the envelope's project token. The renderer must show the count, never label the
    // token as an offending distinct_id.
    test.each([
        [
            'multi-key batch shows the count, not the backfilled token',
            { distinctId: 'phc_token', distinctIdCount: 3 },
            { distinctIdCount: 3 },
        ],
        [
            'single-key batch shows the offending distinct_id',
            { distinctId: 'user-123', distinctIdCount: 1 },
            { distinctId: 'user-123' },
        ],
        [
            'non-string distinctId is ignored in favor of the count',
            { distinctId: { evil: true }, distinctIdCount: 4 },
            { distinctIdCount: 4 },
        ],
        ['string distinctId without a count is shown', { distinctId: 'user-1' }, { distinctId: 'user-1' }],
        ['non-number count without a distinctId yields nothing', { distinctIdCount: 'lots' }, null],
        ['empty details yield nothing', {}, null],
    ])('%s', (_label, details, expected) => {
        expect(resolveHighVolumeOffender(details as Record<string, any>)).toEqual(expected)
    })
})
