import { ErrorTrackingIssue } from '~/queries/schema'

import { mergeIssues } from './utils'

describe('mergeIssues', () => {
    it('arbitrary values', async () => {
        const primaryIssue: ErrorTrackingIssue = {
            id: 'primaryId',
            assignee: { type: 'user', id: 400 },
            description: 'This is the original description',
            name: 'TypeError',
            first_seen: '2024-07-22T13:15:07.074000Z',
            last_seen: '2024-07-20T13:15:50.186000Z',
            occurrences: 250,
            sessions: 100,
            status: 'active',
            users: 50,
            earliest: '',
            volume: [
                '__hx_tag',
                'Sparkline',
                'data',
                [10, 5, 10, 20, 50],
                'labels',
                [
                    '25 Jun, 2024 00:00 (UTC)',
                    '26 Jun, 2024 00:00 (UTC)',
                    '27 Jun, 2024 00:00 (UTC)',
                    '28 Jun, 2024 00:00 (UTC)',
                    '29 Jun, 2024 00:00 (UTC)',
                ],
            ],
        }

        const mergingIssues: ErrorTrackingIssue[] = [
            {
                id: 'secondId',
                assignee: { type: 'user', id: 100 },
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-20T13:15:50.186000Z',
                occurrences: 10,
                sessions: 5,
                status: 'active',
                users: 1,
                earliest: '',
                volume: [
                    '__hx_tag',
                    'Sparkline',
                    'data',
                    [1, 1, 2, 1, 2],
                    'labels',
                    [
                        '25 Jun, 2024 00:00 (UTC)',
                        '26 Jun, 2024 00:00 (UTC)',
                        '27 Jun, 2024 00:00 (UTC)',
                        '28 Jun, 2024 00:00 (UTC)',
                        '29 Jun, 2024 00:00 (UTC)',
                    ],
                ],
            },
            {
                id: 'thirdId',
                assignee: { type: 'user', id: 400 },
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                occurrences: 1,
                sessions: 1,
                status: 'active',
                users: 1,
                earliest: '',
                volume: [
                    '__hx_tag',
                    'Sparkline',
                    'data',
                    [5, 10, 2, 3, 5],
                    'labels',
                    [
                        '25 Jun, 2024 00:00 (UTC)',
                        '26 Jun, 2024 00:00 (UTC)',
                        '27 Jun, 2024 00:00 (UTC)',
                        '28 Jun, 2024 00:00 (UTC)',
                        '29 Jun, 2024 00:00 (UTC)',
                    ],
                ],
            },
            {
                id: 'fourthId',
                assignee: null,
                description: 'This is another description',
                name: 'SyntaxError',
                first_seen: '2023-07-22T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                occurrences: 1000,
                sessions: 500,
                status: 'active',
                users: 50,
                earliest: '',
                volume: [
                    '__hx_tag',
                    'Sparkline',
                    'data',
                    [10, 100, 200, 300, 700],
                    'labels',
                    [
                        '25 Jun, 2024 00:00 (UTC)',
                        '26 Jun, 2024 00:00 (UTC)',
                        '27 Jun, 2024 00:00 (UTC)',
                        '28 Jun, 2024 00:00 (UTC)',
                        '29 Jun, 2024 00:00 (UTC)',
                    ],
                ],
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
            // sums counts
            occurrences: 1261,
            sessions: 606,
            users: 102,
            // sums volumes
            volume: [
                '__hx_tag',
                'Sparkline',
                'data',
                [26, 116, 214, 324, 757],
                'labels',
                [
                    '25 Jun, 2024 00:00 (UTC)',
                    '26 Jun, 2024 00:00 (UTC)',
                    '27 Jun, 2024 00:00 (UTC)',
                    '28 Jun, 2024 00:00 (UTC)',
                    '29 Jun, 2024 00:00 (UTC)',
                ],
            ],
        })
    })
})
