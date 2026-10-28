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
    let folders: string[]
    let folderRequests: URLSearchParams[]
    let metadataRequests: string[]

    beforeEach(() => {
        requests = []
        folders = ['Growth', 'Unfiled', 'Finance', 'Users']
        folderRequests = []
        metadataRequests = []
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
                        folderRequests.push(params)
                        const search = params.get('search')?.toLowerCase() ?? ''
                        const matches = folders.filter((name) => name.toLowerCase().includes(search))
                        const offset = Number(params.get('offset') ?? 0)
                        const limit = Number(params.get('limit') ?? 20)
                        return {
                            results: matches.slice(offset, offset + limit).map(folder),
                            count: matches.length,
                            next: offset + limit < matches.length ? '/next-page' : null,
                        }
                    }
                    if (parent && type) {
                        metadataRequests.push(parent)
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

    it('pages metadata after pin and literal name filters, and reuses metadata across searches', async () => {
        folders = [
            ...Array.from({ length: 22 }, (_, index) => `Collection ${String(index + 1).padStart(2, '0')}`),
            'Growth',
            '-Finance',
        ]
        const logic = analyticsSpacesLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadSpaces()).toDispatchActions(['loadSpacesSuccess'])
        expect(logic.values.spaces).toHaveLength(20)
        expect(logic.values.visibleSpaces[0].name).toBe('Growth')
        expect(logic.values.pagination).toEqual({ offset: 20, hasMore: true })
        expect(folderRequests).toHaveLength(1)
        expect(folderRequests[0].get('limit')).toBe('200')

        await expectLogic(logic, () => {
            logic.actions.loadMore()
            logic.actions.loadMore()
        }).toDispatchActions(['loadSpacesSuccess'])
        expect(logic.values.spaces.map((space) => space.name)).toEqual([...folders].sort((a, b) => a.localeCompare(b)))
        expect(logic.values.pagination).toEqual({ offset: 24, hasMore: false })
        expect(folderRequests).toHaveLength(1)
        expect(metadataRequests).toHaveLength(24 * 4)

        for (const search of ['Collection 22', '-Finance', 'Collection', '-Finance']) {
            await expectLogic(logic, () => logic.actions.setSearch(search)).toDispatchActions(['loadSpacesSuccess'])
            expect(logic.values.visibleSpaces.map((space) => space.name)).toEqual(
                folders.filter((name) => name.includes(search)).slice(0, 20)
            )
        }
        expect(folderRequests).toHaveLength(1)
        expect(metadataRequests).toHaveLength(24 * 4)
    })
})
