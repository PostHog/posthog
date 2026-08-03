import type { PresenceViewerApi } from '~/generated/core/api.schemas'

import { PRESENCE_VIEWER_TTL_MS, dedupeViewersByUser, describePresence, pruneStaleViewers } from './presenceUtils'

const NOW = new Date('2026-08-03T12:00:00Z').getTime()

function viewer(overrides: {
    clientId: string
    userId: number
    name?: string
    activity?: PresenceViewerApi['activity']
    ageMs?: number
}): PresenceViewerApi {
    return {
        client_id: overrides.clientId,
        user: {
            id: overrides.userId,
            email: `${overrides.name?.toLowerCase() ?? `user${overrides.userId}`}@posthog.com`,
            first_name: overrides.name ?? `User ${overrides.userId}`,
        } as PresenceViewerApi['user'],
        activity: overrides.activity ?? 'viewing',
        last_seen_at: new Date(NOW - (overrides.ageMs ?? 0)).toISOString(),
    }
}

describe('presenceUtils', () => {
    it('prunes viewers whose last heartbeat is older than the TTL', () => {
        const viewers = [
            viewer({ clientId: 'fresh', userId: 1, ageMs: 1_000 }),
            viewer({ clientId: 'stale', userId: 2, ageMs: PRESENCE_VIEWER_TTL_MS + 1_000 }),
        ]

        expect(pruneStaleViewers(viewers, NOW).map((v) => v.client_id)).toEqual(['fresh'])
    })

    it("collapses one user's tabs into a single viewer, preferring the composing tab", () => {
        const viewers = [
            viewer({ clientId: 'idle-tab', userId: 1, name: 'Luke', ageMs: 0 }),
            viewer({ clientId: 'writing-tab', userId: 1, name: 'Luke', activity: 'composing', ageMs: 6_000 }),
        ]

        const deduped = dedupeViewersByUser(viewers)

        expect(deduped).toHaveLength(1)
        expect(deduped[0].client_id).toEqual('writing-tab')
        expect(deduped[0].activity).toEqual('composing')
    })

    it('keeps the freshest tab when neither is composing', () => {
        const viewers = [
            viewer({ clientId: 'old-tab', userId: 1, ageMs: 9_000 }),
            viewer({ clientId: 'new-tab', userId: 1, ageMs: 1_000 }),
        ]

        expect(dedupeViewersByUser(viewers).map((v) => v.client_id)).toEqual(['new-tab'])
    })

    describe('describePresence', () => {
        it('returns null when nobody else is here', () => {
            expect(describePresence([], 'this ticket')).toBeNull()
        })

        const cases: [string, PresenceViewerApi[], string][] = [
            ['one viewing', [viewer({ clientId: 'a', userId: 1, name: 'Anna' })], 'Anna is viewing this ticket'],
            [
                'one composing',
                [viewer({ clientId: 'a', userId: 1, name: 'Luke', activity: 'composing' })],
                'Luke is replying...',
            ],
            [
                'two viewing',
                [
                    viewer({ clientId: 'a', userId: 1, name: 'Anna' }),
                    viewer({ clientId: 'b', userId: 2, name: 'Luke' }),
                ],
                'Anna and Luke are viewing this ticket',
            ],
            [
                'two, one composing',
                [
                    viewer({ clientId: 'a', userId: 1, name: 'Anna' }),
                    viewer({ clientId: 'b', userId: 2, name: 'Luke', activity: 'composing' }),
                ],
                'Luke is replying..., Anna is viewing',
            ],
            [
                'three viewing',
                [
                    viewer({ clientId: 'a', userId: 1, name: 'Anna' }),
                    viewer({ clientId: 'b', userId: 2, name: 'Luke' }),
                    viewer({ clientId: 'c', userId: 3, name: 'Sam' }),
                ],
                'Anna, Luke and 1 other are viewing this ticket',
            ],
            [
                'four, one composing',
                [
                    viewer({ clientId: 'a', userId: 1, name: 'Anna' }),
                    viewer({ clientId: 'b', userId: 2, name: 'Luke', activity: 'composing' }),
                    viewer({ clientId: 'c', userId: 3, name: 'Sam' }),
                    viewer({ clientId: 'd', userId: 4, name: 'Kim' }),
                ],
                'Luke is replying..., 3 others are viewing',
            ],
        ]

        it.each(cases)('describes %s', (_name, viewers, expected) => {
            expect(describePresence(dedupeViewersByUser(viewers), 'this ticket')).toEqual(expected)
        })
    })
})
