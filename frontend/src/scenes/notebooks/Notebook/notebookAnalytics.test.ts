import { AccessControlLevel, UserType } from '~/types'

import { NotebookType } from '../types'
import {
    NOTEBOOK_SIZE_PROPERTY_KEYS,
    NotebookOpenedProperties,
    buildNotebookOpenedEvent,
    buildNotebookSizeProperties,
} from './notebookAnalytics'

describe('notebookAnalytics', () => {
    const user = { uuid: 'user-1' } as UserType

    const notebook = (overrides: Partial<NotebookType> = {}): NotebookType =>
        ({
            short_id: 'abc123',
            created_by: { uuid: 'user-1' },
            user_access_level: AccessControlLevel.Editor,
            content: { type: 'doc', content: [{}, {}, {}] },
            ...overrides,
        }) as NotebookType

    describe('buildNotebookOpenedEvent', () => {
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

    describe('buildNotebookSizeProperties', () => {
        const sizes = { cellCount: 6, codeCellCount: 2, charLength: 480 }

        it('maps the size dimensions for a real notebook', () => {
            expect(buildNotebookSizeProperties(notebook(), false, sizes)).toEqual({
                notebook_short_id: 'abc123',
                notebook_cell_count: 6,
                notebook_code_cell_count: 2,
                notebook_char_length: 480,
            })
        })

        it.each([
            ['no notebook loaded', null, false],
            ['scratchpad', 'scratchpad', false],
            ['template', 'template-onboarding', false],
            ['an anonymous shared view', 'abc123', true],
        ])('returns null for %s so its size never registers', (_label, shortId, isShared) => {
            const nb = shortId === null ? null : notebook({ short_id: shortId })
            expect(buildNotebookSizeProperties(nb, isShared, sizes)).toBeNull()
        })

        // Guards the pollution risk: the keys we register must match the keys `beforeUnmount`
        // unregisters. If the two drift, a size property leaks onto events on other pages.
        it('emits exactly the keys listed for unregister', () => {
            const properties = buildNotebookSizeProperties(notebook(), false, sizes)
            expect(Object.keys(properties ?? {}).sort()).toEqual([...NOTEBOOK_SIZE_PROPERTY_KEYS].sort())
        })
    })
})
