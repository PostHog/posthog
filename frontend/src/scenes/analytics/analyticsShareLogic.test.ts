import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { analyticsShareLogic } from './analyticsShareLogic'
import { AnalyticsSpace } from './analyticsSpacesLogic'

describe('analyticsShareLogic', () => {
    let moves: string[]

    beforeEach(() => {
        moves = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': { results: [] },
                '/api/projects/:team_id/canvases/:id/': ({ params }) => ({ id: params.id, channel: `ch-${params.id}` }),
                '/api/projects/:team_id/task_channels/:id/': ({ params }) => ({
                    id: params.id,
                    channel_type: params.id === 'ch-c2' ? 'personal' : 'public',
                }),
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const ref = params.get('ref')
                    return ref
                        ? {
                              results: [{ id: `fs-${ref}`, type: 'insight/trends', ref, path: `Growth/${ref}` }],
                              next: null,
                          }
                        : { results: [], count: 0, next: null }
                },
            },
            post: {
                '/api/projects/:team_id/file_system/:id/move/': async ({ params, request }) => {
                    const body = (await request.json()) as { new_path: string }
                    moves.push(`${params.id} -> ${body.new_path}`)
                    return { id: params.id, path: body.new_path }
                },
            },
        })
        initKeaTests()
    })

    const FINANCE: AnalyticsSpace = {
        path: 'Finance',
        name: 'Finance',
        counts: { canvas: 0, dashboard: 0, insight: 0, notebook: 0 },
        total: 0,
        lastAddedAt: null,
    }

    // The new path decides who sees the item, and a slash in a name would otherwise become a folder.
    test.each([
        ['insight', 'Weekly/active', FINANCE, 'fs-i1 -> Finance/Weekly\\/active'],
        ['canvas', 'Run rate', FINANCE, 'fs-c1 -> Finance/Run rate'],
        ['canvas', 'Run rate', null, 'fs-c1 -> Unfiled/Canvases/Run rate'],
        ['dashboard', 'Board', null, 'fs-d1 -> Unfiled/Dashboards/Board'],
    ] as const)('moves a %s named %p into %p', async (type, name, space, expected) => {
        const logic = analyticsShareLogic()
        logic.mount()
        const ref = `${type[0]}1`
        await expectLogic(logic, () => logic.actions.moveItem({ type, ref, name }, space)).toDispatchActions([
            'shareToSpaceDone',
        ])

        expect(moves).toEqual([expected])
        expect(logic.values.itemSpaces[`${type}:${ref}`]).toBe(space?.name ?? null)
    })

    it('refuses to share a canvas from a private channel, since the space would not make it visible', async () => {
        const logic = analyticsShareLogic()
        logic.mount()
        await expectLogic(logic, () =>
            logic.actions.moveItem({ type: 'canvas', ref: 'c2', name: 'Private' }, FINANCE)
        ).toDispatchActions(['shareToSpaceDone'])

        expect(moves).toEqual([])
        expect(logic.values.itemSpaces['canvas:c2']).toBeUndefined()
    })
})
