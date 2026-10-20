import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { analyticsSpacesLogic } from './analyticsSpacesLogic'

// Ids stay slash-free so the mocked detail route matches them.
const folder = (path: string): Record<string, unknown> => ({
    id: `fs-${path.replace('/', '-')}`,
    type: 'folder',
    path,
    meta: {},
})
const row = (type: string, ref: string, path: string): Record<string, unknown> => ({
    id: `fs-${ref}`,
    type,
    ref,
    path,
    created_at: '2026-09-01T00:00:00Z',
    meta: {},
})

describe('analyticsSpacesLogic', () => {
    let requests: string[]

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [
                        { id: 'sc-home', type: 'folder', path: 'Ada', ref: 'Users/Ada' },
                        { id: 'sc-growth', type: 'folder', path: 'Growth', ref: 'Growth' },
                    ],
                },
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const parent = params.get('parent')
                    const type = params.get('type') ?? params.get('type__startswith')
                    if (params.get('depth') === '1' && type === 'folder') {
                        return {
                            results: ['Growth', 'Unfiled', 'Finance', 'Users'].map(folder),
                            count: 4,
                            next: null,
                        }
                    }
                    if (parent && type) {
                        // Per-type counts come from `count`, not from the one row the page holds.
                        const count = parent === 'Growth' ? ({ insight: 7, dashboard: 2 }[type] ?? 0) : 0
                        return { results: count ? [row(type, `${type}-x`, `${parent}/X`)] : [], count, next: null }
                    }
                    return { results: [], count: 0, next: null }
                },
            },
            delete: {
                '/api/projects/:team_id/file_system_shortcut/:id/': ({ params }) => {
                    requests.push(`delete shortcut ${params.id}`)
                    return [204, null]
                },
            },
        })
        initKeaTests()
    })

    it('lists spaces alphabetically with counts from the API, pinned ones first, leaving out Unfiled and Users', async () => {
        const logic = analyticsSpacesLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.loadShortcuts()
            logic.actions.loadSpaces()
        }).toDispatchActions(['loadShortcutsSuccess', 'loadSpacesSuccess'])

        expect(logic.values.spaces.map((space) => [space.name, space.total])).toEqual([
            ['Finance', 0],
            ['Growth', 9],
        ])
        expect(logic.values.spaces[1].counts).toEqual({ canvas: 0, dashboard: 2, insight: 7, notebook: 0 })
        // The shortcut's ref names the folder; a home folder shortcut is not a space.
        expect(logic.values.pinnedSpaces.map((space) => space.path)).toEqual(['Growth'])
        expect(logic.values.visibleSpaces.map((space) => space.name)).toEqual(['Growth', 'Finance'])
        logic.actions.setSearch('fin')
        expect(logic.values.visibleSpaces.map((space) => space.name)).toEqual(['Finance'])
    })

    it('drops the pin of a collection deleted through the project tree, and only for a top-level folder', async () => {
        const logic = analyticsSpacesLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadShortcuts()).toDispatchActions(['loadShortcutsSuccess'])

        logic.actions.deleteSavedItem({ id: 'fs-Growth-Q4', type: 'folder', path: 'Growth/Q4' } as FileSystemEntry)
        await expectLogic(logic, () =>
            logic.actions.deleteSavedItem({ id: 'fs-Growth', type: 'folder', path: 'Growth' } as FileSystemEntry)
        ).toDispatchActions(['loadShortcuts'])

        expect(requests).toEqual(['delete shortcut sc-growth'])
    })
})
