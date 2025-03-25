import { ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { generateSparklineLabels, mergeIssues } from './utils'

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
    it('generate labels from with hour resolution', async () => {
        const labels = generateSparklineLabels(
            {
                date_from: '2025-01-01',
                date_to: '2025-01-02',
            },
            24
        )
        expect(labels).toEqual([
            '2025-01-01T00:00:00.000Z',
            '2025-01-01T01:00:00.000Z',
            '2025-01-01T02:00:00.000Z',
            '2025-01-01T03:00:00.000Z',
            '2025-01-01T04:00:00.000Z',
            '2025-01-01T05:00:00.000Z',
            '2025-01-01T06:00:00.000Z',
            '2025-01-01T07:00:00.000Z',
            '2025-01-01T08:00:00.000Z',
            '2025-01-01T09:00:00.000Z',
            '2025-01-01T10:00:00.000Z',
            '2025-01-01T11:00:00.000Z',
            '2025-01-01T12:00:00.000Z',
            '2025-01-01T13:00:00.000Z',
            '2025-01-01T14:00:00.000Z',
            '2025-01-01T15:00:00.000Z',
            '2025-01-01T16:00:00.000Z',
            '2025-01-01T17:00:00.000Z',
            '2025-01-01T18:00:00.000Z',
            '2025-01-01T19:00:00.000Z',
            '2025-01-01T20:00:00.000Z',
            '2025-01-01T21:00:00.000Z',
            '2025-01-01T22:00:00.000Z',
            '2025-01-01T23:00:00.000Z',
        ])
    })
})
