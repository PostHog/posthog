import { getRecordingExpiryDeadline } from './recordingExpiryDialog'

describe('getRecordingExpiryDeadline', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-12T22:00:00.000Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test.each([
        { name: 'several days left', ttlDays: 4, expected: 'in 4 days' },
        { name: 'one day left', ttlDays: 1, expected: 'in 1 day' },
        { name: 'expires today', ttlDays: 0, expected: 'today' },
        { name: 'already past the expiry date', ttlDays: -2, expected: 'today' },
    ])('says $name', ({ ttlDays, expected }) => {
        expect(getRecordingExpiryDeadline(ttlDays).inWords).toEqual(expected)
    })

    // The count and the date have to come off expiry_time on one clock. The API counts UTC calendar days,
    // so the recording_ttl of 3 below can name a different day than the date the dialog prints.
    test.each([
        {
            name: 'several days left',
            expiryTime: '2026-09-15T00:00:00.000000Z',
            expected: { inWords: 'in 3 days', onDate: 'September 15, 2026' },
        },
        {
            name: 'one day left',
            expiryTime: '2026-09-13T12:00:00.000000Z',
            expected: { inWords: 'in 1 day', onDate: 'September 13, 2026' },
        },
        {
            name: 'the last hours of the final day',
            expiryTime: '2026-09-12T23:00:00.000000Z',
            expected: { inWords: 'today', onDate: null },
        },
    ])('reads the deadline off the expiry time with $name', ({ expiryTime, expected }) => {
        expect(getRecordingExpiryDeadline(3, expiryTime)).toEqual(expected)
    })

    test.each([
        { name: 'the recording has no expiry time', ttlDays: 4, expiryTime: undefined },
        { name: 'the expiry time cannot be parsed', ttlDays: 4, expiryTime: 'not a timestamp' },
    ])('has no date when $name', ({ ttlDays, expiryTime }) => {
        expect(getRecordingExpiryDeadline(ttlDays, expiryTime).onDate).toBeNull()
    })
})
