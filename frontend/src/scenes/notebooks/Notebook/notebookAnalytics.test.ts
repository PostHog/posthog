import { AccessControlLevel, UserType } from '~/types'

import { NotebookType } from '../types'
import { buildNotebookOpenedEvent } from './notebookAnalytics'

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

    it('flags the creator and counts top-level nodes for a direct open', () => {
        expect(buildNotebookOpenedEvent(notebook(), user, false)).toEqual({
            short_id: 'abc123',
            is_creator: true,
            user_access_level: AccessControlLevel.Editor,
            access_source: 'direct',
            node_count: 3,
        })
    })

    it('marks a viewer of another user’s notebook via shared link', () => {
        const event = buildNotebookOpenedEvent(notebook({ created_by: { uuid: 'other' } as UserType }), user, true)
        expect(event).toMatchObject({ is_creator: false, access_source: 'shared_link' })
    })

    it('handles a notebook with no content and no creator', () => {
        const event = buildNotebookOpenedEvent(notebook({ content: null, created_by: null }), user, false)
        expect(event).toMatchObject({ is_creator: false, node_count: 0 })
    })

    it.each([
        ['scratchpad', 'scratchpad'],
        ['template', 'template-onboarding'],
        ['no notebook loaded', undefined],
    ])('does not emit for %s', (_label, shortId) => {
        const nb = shortId === undefined ? null : notebook({ short_id: shortId })
        expect(buildNotebookOpenedEvent(nb, user, false)).toBeNull()
    })
})
