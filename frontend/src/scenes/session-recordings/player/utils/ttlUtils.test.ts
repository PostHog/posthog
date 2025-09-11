import { calculateTTL } from './ttlUtils'

describe('calculateTTL', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        {
            description: 'returns full retention period for recording from today',
            recordingStartTime: '2023-01-01T00:00:00.000Z',
            retentionPeriodDays: 30,
            currentTime: '2023-01-01T00:00:00.000Z',
            expectedTTL: 30,
        },
        {
            description: 'returns remaining days when recording is 5 days old',
            recordingStartTime: '2023-01-01T00:00:00.000Z',
            retentionPeriodDays: 30,
            currentTime: '2023-01-06T00:00:00.000Z',
            expectedTTL: 25,
        },
        {
            description: 'returns 0 when recording has reached retention period',
            recordingStartTime: '2023-01-01T00:00:00.000Z',
            retentionPeriodDays: 30,
            currentTime: '2023-01-31T00:00:00.000Z',
            expectedTTL: 0,
        },
        {
            description: 'returns 0 when recording has exceeded retention period',
            recordingStartTime: '2023-01-01T00:00:00.000Z',
            retentionPeriodDays: 30,
            currentTime: '2023-02-05T00:00:00.000Z',
            expectedTTL: 0,
        },
        {
            description: 'handles partial days correctly',
            recordingStartTime: '2023-01-01T12:00:00.000Z',
            retentionPeriodDays: 7,
            currentTime: '2023-01-02T06:00:00.000Z',
            expectedTTL: 7,
        },
        {
            description: 'works with short retention period',
            recordingStartTime: '2023-01-01T00:00:00.000Z',
            retentionPeriodDays: 1,
            currentTime: '2023-01-01T23:59:59.999Z',
            expectedTTL: 1,
        },
        {
            description: 'works with long retention period',
            recordingStartTime: '2023-01-01T00:00:00.000Z',
            retentionPeriodDays: 365,
            currentTime: '2023-06-01T00:00:00.000Z',
            expectedTTL: 214,
        },
    ])('$description', ({ recordingStartTime, retentionPeriodDays, currentTime, expectedTTL }) => {
        jest.setSystemTime(new Date(currentTime))

        const result = calculateTTL(recordingStartTime, retentionPeriodDays)

        expect(result).toBe(expectedTTL)
    })
})
