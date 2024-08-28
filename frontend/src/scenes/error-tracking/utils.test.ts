import { ErrorTrackingGroup } from '~/queries/schema'

import { mergeGroups } from './utils'

describe('mergeGroups', () => {
    it('arbitrary values', async () => {
        const primaryGroup: ErrorTrackingGroup = {
            assignee: 400,
            description: 'This is the original description',
            exception_type: 'TypeError',
            fingerprint: ['Fingerprint'],
            first_seen: '2024-07-22T13:15:07.074000Z',
            last_seen: '2024-07-20T13:15:50.186000Z',
            merged_fingerprints: [['ExistingFingerprint']],
            occurrences: 250,
            sessions: 100,
            status: 'active',
            users: 50,
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

        const mergingGroups: ErrorTrackingGroup[] = [
            {
                assignee: 100,
                description: 'This is another description',
                exception_type: 'SyntaxError',
                fingerprint: ['Fingerprint2'],
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-20T13:15:50.186000Z',
                merged_fingerprints: [['NestedFingerprint']],
                occurrences: 10,
                sessions: 5,
                status: 'active',
                users: 1,
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
                assignee: 400,
                description: 'This is another description',
                exception_type: 'SyntaxError',
                fingerprint: ['Fingerprint3'],
                first_seen: '2024-07-21T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                merged_fingerprints: [],
                occurrences: 1,
                sessions: 1,
                status: 'active',
                users: 1,
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
                assignee: null,
                description: 'This is another description',
                exception_type: 'SyntaxError',
                fingerprint: ['Fingerprint4'],
                first_seen: '2023-07-22T13:15:07.074000Z',
                last_seen: '2024-07-22T13:15:50.186000Z',
                merged_fingerprints: [],
                occurrences: 1000,
                sessions: 500,
                status: 'active',
                users: 50,
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

        const mergedGroup = mergeGroups(primaryGroup, mergingGroups)

        expect(mergedGroup).toEqual({
            // retains values from primary group
            assignee: 400,
            description: 'This is the original description',
            exception_type: 'TypeError',
            fingerprint: ['Fingerprint'],
            status: 'active',
            // earliest first_seen
            first_seen: '2023-07-22T13:15:07.074Z',
            // latest last_seen
            last_seen: '2024-07-22T13:15:50.186Z',
            // retains previously merged_fingerprints
            // adds new fingerprints AND their nested fingerprints
            merged_fingerprints: [
                ['ExistingFingerprint'],
                ['Fingerprint2'],
                ['NestedFingerprint'],
                ['Fingerprint3'],
                ['Fingerprint4'],
            ],
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
