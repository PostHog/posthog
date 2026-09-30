import { dayjs } from 'lib/dayjs'

import { TaskListItemApi, TaskUserBasicInfoApi } from 'products/tasks/frontend/generated/api.schemas'

import { spacePresence } from './todaySpaceAuthors'

const NOW = dayjs('2026-03-10T12:00:00Z')
const ME = 1

const user = (id: number): TaskUserBasicInfoApi => ({ id }) as TaskUserBasicInfoApi

const session = (
    channel: string | null,
    authorId: number,
    minutesAgo: number,
    extra: Partial<TaskListItemApi> = {}
): TaskListItemApi =>
    ({
        id: `${channel}-${authorId}-${minutesAgo}`,
        channel,
        created_by: user(authorId),
        last_activity_at: NOW.subtract(minutesAgo, 'minute').toISOString(),
        archived: false,
        ...extra,
    }) as TaskListItemApi

describe('spacePresence', () => {
    it('lists each other author once per space, live authors first, and drops stale, archived, and own sessions', () => {
        const presence = spacePresence(
            [
                session('space-a', 2, 60 * 3),
                session('space-a', 2, 5 * 60 * 24),
                session('space-a', 3, 2),
                session('space-a', 4, 60 * 24 * 8),
                session('space-a', 5, 1, { archived: true }),
                session('space-a', ME, 1),
                session('space-b', 2, 9),
                session(null, 6, 1),
            ],
            ME,
            NOW
        )

        expect(
            Object.fromEntries(
                Object.entries(presence).map(([spaceId, authors]) => [
                    spaceId,
                    authors.map((author) => [author.user.id, author.live]),
                ])
            )
        ).toEqual({
            'space-a': [
                [3, true],
                [2, false],
            ],
            'space-b': [[2, true]],
        })
    })
})
