import { LiveEvent } from '~/types'

import { pruneRecentUsersByLastSeen, upsertRecentUsersByLastSeenFromEvents } from './recentUsersByLastSeen'

const toLiveEvent = (distinctId: string, timestamp: string): LiveEvent =>
    ({
        distinct_id: distinctId,
        timestamp,
    }) as LiveEvent

describe('recentUsersByLastSeen', () => {
    describe('pruneRecentUsersByLastSeen', () => {
        it('drops users seen more than 60 seconds ago', () => {
            const nowTs = new Date('2026-01-16T16:30:00Z').getTime() / 1000
            const recentUsersByLastSeen = new Map<string, number>([
                ['fresh-user', nowTs - 59],
                ['expired-user', nowTs - 61],
                ['boundary-user', nowTs - 60],
            ])

            expect(pruneRecentUsersByLastSeen(recentUsersByLastSeen, nowTs)).toEqual(
                new Map<string, number>([['fresh-user', nowTs - 59]])
            )
        })

        it('returns the original map when nothing expires', () => {
            const nowTs = new Date('2026-01-16T16:30:00Z').getTime() / 1000
            const recentUsersByLastSeen = new Map<string, number>([['fresh-user', nowTs - 5]])

            expect(pruneRecentUsersByLastSeen(recentUsersByLastSeen, nowTs)).toBe(recentUsersByLastSeen)
        })
    })

    describe('upsertRecentUsersByLastSeenFromEvents', () => {
        it('keeps the newest timestamp per user for post-handoff events', () => {
            const newerThan = new Date('2026-01-16T16:29:00Z')
            const recentUsersByLastSeen = new Map<string, number>([['existing-user', newerThan.getTime() / 1000 + 10]])

            expect(
                upsertRecentUsersByLastSeenFromEvents(
                    recentUsersByLastSeen,
                    [
                        toLiveEvent('existing-user', '2026-01-16T16:29:20Z'),
                        toLiveEvent('existing-user', '2026-01-16T16:29:10Z'),
                        toLiveEvent('new-user', '2026-01-16T16:29:30Z'),
                    ],
                    newerThan
                )
            ).toEqual(
                new Map<string, number>([
                    ['existing-user', new Date('2026-01-16T16:29:20Z').getTime() / 1000],
                    ['new-user', new Date('2026-01-16T16:29:30Z').getTime() / 1000],
                ])
            )
        })

        it('ignores overlap events at or before the handoff', () => {
            const newerThan = new Date('2026-01-16T16:29:00Z')
            const recentUsersByLastSeen = new Map<string, number>()

            expect(
                upsertRecentUsersByLastSeenFromEvents(
                    recentUsersByLastSeen,
                    [toLiveEvent('overlap-user', '2026-01-16T16:29:00Z')],
                    newerThan
                )
            ).toBe(recentUsersByLastSeen)
        })
    })
})
