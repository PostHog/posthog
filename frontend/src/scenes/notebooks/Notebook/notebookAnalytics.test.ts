import { AccessControlLevel, UserType } from '~/types'

import { NotebookType } from '../types'
import { NotebookOpenedProperties, buildNotebookOpenedEvent } from './notebookAnalytics'

describe('buildNotebookOpenedEvent', () => {
    const user = { uuid: 'user-1' } as UserType

    const notebook = (overrides: Partial<NotebookType> = {}): NotebookType =>
        ({
            short_id: 'abc123',
            created_by: { uuid: 'user-1' },
            user_access_level: AccessControlLevel.Editor,
            content: { type: 'doc', content: [{}, {}, {}] },
            ...overrides,
        }) as NotebookType

    it.each([
        [
            'the creator opening directly (counts top-level nodes)',
            {},
            false,
            {
                short_id: 'abc123',
                is_creator: true,
                user_access_level: AccessControlLevel.Editor,
                access_source: 'direct',
                node_count: 3,
            },
        ],
        [
            'a viewer of another user’s notebook via shared link',
            { created_by: { uuid: 'other' } as UserType },
            true,
            { is_creator: false, access_source: 'shared_link' },
        ],
        [
            'a notebook with no content and no creator',
            { content: null, created_by: null },
            false,
            { is_creator: false, node_count: 0 },
        ],
    ] as [string, Partial<NotebookType>, boolean, Partial<NotebookOpenedProperties>][])(
        'builds the event for %s',
        (_label, overrides, isShared, expected) => {
            expect(buildNotebookOpenedEvent(notebook(overrides), user, isShared)).toMatchObject(expected)
        }
    )

    it.each([
        ['scratchpad', 'scratchpad'],
        ['template', 'template-onboarding'],
        ['no notebook loaded', undefined],
    ])('does not emit for %s', (_label, shortId) => {
        const nb = shortId === undefined ? null : notebook({ short_id: shortId })
        expect(buildNotebookOpenedEvent(nb, user, false)).toBeNull()
    })
})
