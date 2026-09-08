import { getRecordingExpiryDeadline } from './recordingExpiryDialog'

describe('getRecordingExpiryDeadline', () => {
    test.each([
        { name: 'several days left', ttlDays: 4, expected: 'in 4 days' },
        { name: 'one day left', ttlDays: 1, expected: 'in 1 day' },
        { name: 'expires today', ttlDays: 0, expected: 'today' },
        { name: 'already past the expiry date', ttlDays: -2, expected: 'today' },
    ])('says $name', ({ ttlDays, expected }) => {
        expect(getRecordingExpiryDeadline(ttlDays).inWords).toEqual(expected)
    })

    it('formats the expiry date', () => {
        expect(getRecordingExpiryDeadline(4, '2023-06-01T00:00:00.000000Z').onDate).toEqual('June 1, 2023')
    })

    test.each([
        { name: 'the recording has no expiry time', ttlDays: 4, expiryTime: undefined },
        { name: 'the recording expires today', ttlDays: 0, expiryTime: '2023-06-01T00:00:00.000000Z' },
    ])('has no date when $name', ({ ttlDays, expiryTime }) => {
        expect(getRecordingExpiryDeadline(ttlDays, expiryTime).onDate).toBeNull()
    })
})
