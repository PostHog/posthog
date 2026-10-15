import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
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
    let rows: Record<string, unknown>[]
    let moveSucceeds: boolean

    beforeEach(() => {
        requests = []
        moveSucceeds = true
        rows = [row('insight/trends', 'i1', 'Scratch/Inner/I'), row('canvas', 'c1', 'Scratch/C')]
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const parent = params.get('parent')
                    const type = params.get('type') ?? params.get('type__startswith')
                    if (params.get('path')) {
                        return { results: [folder(params.get('path')!)], count: 1, next: null }
                    }
                    if (params.get('depth') === '1' && type === 'folder') {
                        return {
                            results: ['Growth', 'Unfiled', 'Finance', 'Users'].map(folder),
                            count: 4,
                            next: null,
                        }
                    }
                    if (parent && type === 'folder') {
                        return { results: [folder(`${parent}/Inner`)], count: 1, next: null }
                    }
                    if (parent && params.get('not_type') === 'folder') {
                        const inside = rows.filter((entry) => String(entry.path).startsWith(`${parent}/`))
                        return { results: inside, count: inside.length, next: null }
                    }
                    if (parent && type) {
                        // Per-type counts come from `count`, not from the one row the page holds.
                        const count = parent === 'Growth' ? ({ insight: 7, dashboard: 2 }[type] ?? 0) : 0
                        return { results: count ? [row(type, `${type}-x`, `${parent}/X`)] : [], count, next: null }
                    }
                    return { results: [], count: 0, next: null }
                },
            },
            post: {
                '/api/projects/:team_id/file_system/:id/move/': async ({ params, request }) => {
                    const body = (await request.json()) as { new_path: string }
                    requests.push(`move ${params.id} -> ${body.new_path}`)
                    if (moveSucceeds) {
                        rows = rows.filter((entry) => entry.id !== params.id)
                    }
                    return { id: params.id, path: body.new_path }
                },
            },
            delete: {
                '/api/projects/:team_id/file_system/:id/': ({ params, request }) => {
                    requests.push(`delete ${params.id} recursive=${new URL(request.url).searchParams.get('recursive')}`)
                    return [204, null]
                },
            },
        })
        initKeaTests()
    })

    it('lists spaces alphabetically with counts from the API, leaving out Unfiled and Users', async () => {
        const logic = analyticsSpacesLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadSpaces()).toDispatchActions(['loadSpacesSuccess'])

        expect(logic.values.spaces.map((space) => [space.name, space.total])).toEqual([
            ['Finance', 0],
            ['Growth', 9],
        ])
        expect(logic.values.spaces[1].counts).toEqual({ canvas: 0, dashboard: 2, insight: 7, notebook: 0 })
    })

    it('empties a space to unfiled, then removes its folders deepest first without a recursive delete', async () => {
        const logic = analyticsSpacesLogic()
        logic.mount()
        logic.actions.openDeleteSpace({ path: 'Scratch', name: 'Scratch' })
        await expectLogic(logic, () => logic.actions.deleteSpace()).toDispatchActions(['deleteSpaceDone'])

        expect(requests).toEqual([
            'move fs-i1 -> Unfiled/Insights/I',
            'move fs-c1 -> Unfiled/Canvases/C',
            'delete fs-Scratch-Inner recursive=false',
            'delete fs-Scratch recursive=false',
        ])
        expect(logic.values.deletingSpace).toBeNull()
        expect(router.values.location.pathname).toContain(urls.analyticsSpaces())
    })

    it('keeps the space when something inside could not be moved out', async () => {
        moveSucceeds = false
        const logic = analyticsSpacesLogic()
        logic.mount()
        logic.actions.openDeleteSpace({ path: 'Scratch', name: 'Scratch' })
        await expectLogic(logic, () => logic.actions.deleteSpace()).toDispatchActions(['deleteSpaceDone'])

        expect(requests.filter((request) => request.startsWith('delete'))).toEqual([])
        expect(logic.values.deletingSpace).toEqual({ path: 'Scratch', name: 'Scratch' })
    })
})
