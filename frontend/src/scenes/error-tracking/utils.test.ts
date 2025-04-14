import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { generateDateRangeLabel, generateSparklineLabels, mergeIssues, resolveDate, resolveDateRange } from './utils'

describe('mergeIssues', () => {
    it('arbitrary values', async () => {
        const primaryIssue: ErrorTrackingIssue = {
            id: 'primaryId',
            assignee: { type: 'user', id: 400 },
            description: 'This is the original description',
            name: 'TypeError',
            first_seen: '2024-07-22T13:15:07.074000Z',
            last_seen: '2024-07-20T13:15:50.186000Z',
            aggregations: {
                occurrences: 250,
                sessions: 100,
                users: 50,
                volumeDay: [10, 5, 10, 20, 50],
                volumeRange: [0, 0, 10, 25, 95],
            },
            status: 'active',
            earliest: '',
        }

        const mergingIssues: ErrorTrackingIssue[] = [
            {
                id: 'secondId',
                assignee: { type: 'user', id: 100 },
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-20T13:15:50.186000Z',
                aggregations: {
                    occurrences: 10,
                    sessions: 5,
                    users: 1,
                    volumeDay: [1, 1, 2, 1, 2],
                    volumeRange: [0, 0, 0, 0, 1],
                },
                status: 'active',
                earliest: '',
            },
            {
                id: 'thirdId',
                assignee: { type: 'user', id: 400 },
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                aggregations: {
                    occurrences: 1,
                    sessions: 1,
                    users: 1,
                    volumeDay: [5, 10, 2, 3, 5],
                    volumeRange: [0, 0, 0, 1, 0],
                },
                status: 'active',
                earliest: '',
            },
            {
                id: 'fourthId',
                assignee: null,
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2023-07-22T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                aggregations: {
                    occurrences: 1000,
                    sessions: 500,
                    users: 50,
                    volumeDay: [10, 100, 200, 300, 700],
                    volumeRange: [0, 500, 1500, 1000, 1310],
                },
                status: 'active',
                earliest: '',
            },
        ]

        const mergedIssue = mergeIssues(primaryIssue, mergingIssues)

        expect(mergedIssue).toEqual({
            // retains values from primary group
            id: 'primaryId',
            assignee: { type: 'user', id: 400 },
            description: 'This is the original description',
            earliest: '',
            name: 'TypeError',
            status: 'active',
            // earliest first_seen
            first_seen: '2023-07-22T13:15:07.074Z',
            // latest last_seen
            last_seen: '2024-07-22T13:15:50.186Z',
            aggregations: {
                // sums counts
                occurrences: 1261,
                sessions: 606,
                users: 102,
                // sums volumes
                volumeDay: [26, 116, 214, 324, 757],
                volumeRange: [0, 500, 1510, 1026, 1406],
            },
        })
    })
})

describe('generate sparkline labels', () => {
    beforeAll(() => {
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))
    })

    it('generate labels from with hour resolution', async () => {
        const labels = generateSparklineLabels(
            {
                date_from: '2025-01-01',
                date_to: '2025-01-02',
            },
            4
        ).map((label) => label.toISOString())
        expect(labels).toEqual([
            '2025-01-01T00:00:00.000Z',
            '2025-01-01T06:00:00.000Z',
            '2025-01-01T12:00:00.000Z',
            '2025-01-01T18:00:00.000Z',
        ])
    })

    it('test date range resolution', async () => {
        const range = {
            date_from: '-7d',
            date_to: '-1d',
        }
        const resolvedRange = resolveDateRange(range)
        expect(resolvedRange.date_from.toISOString()).toEqual('2023-01-03T17:22:08.000Z')
        expect(resolvedRange.date_to.toISOString()).toEqual('2023-01-09T17:22:08.000Z')
    })

    it('test date resolution', async () => {
        const resolvedDate = resolveDate('yStart')
        expect(resolvedDate.toISOString()).toEqual('2023-01-01T00:00:00.000Z')
    })

    it('test date range label generation', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-7d',
        })
        expect(rangeLabel).toEqual('7d')
    })
})

describe('date range label generation', () => {
    it('-7d', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-7d',
        })
        expect(rangeLabel).toEqual('7d')
    })

    it('-24h', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-24h',
        })
        expect(rangeLabel).toEqual('24h')
    })

    it('-3h', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '-3h',
        })
        expect(rangeLabel).toEqual('3h')
    })

    it('01-01-2025', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: '01-01-2025',
        })
        expect(rangeLabel).toEqual('Custom')
    })

    it('yStart', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: 'yStart',
        })
        expect(rangeLabel).toEqual('Year')
    })

    it('mStart', async () => {
        const rangeLabel = generateDateRangeLabel({
            date_from: 'mStart',
        })
        expect(rangeLabel).toEqual('Month')
    })
})
