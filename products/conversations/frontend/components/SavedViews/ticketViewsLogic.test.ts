import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SavedTicketView } from '../../types'
import { folderNodeId } from './ticketViewFolders'
import { ticketViewsLogic } from './ticketViewsLogic'

const makeView = (shortId: string, folder: string): SavedTicketView => ({
    id: shortId,
    short_id: shortId,
    name: `View ${shortId}`,
    filters: {},
    folder,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    is_favorited: false,
})

describe('ticketViewsLogic', () => {
    let logic: ReturnType<typeof ticketViewsLogic.build>
    let views: SavedTicketView[]
    let movePayloads: Record<string, string>[]

    beforeEach(() => {
        localStorage.clear()
        views = [makeView('parent', 'Escalations'), makeView('child', 'Escalations/EU')]
        movePayloads = []

        useMocks({
            get: {
                '/api/projects/:team_id/conversations/views/': () => [200, { results: views }],
            },
            post: {
                '/api/projects/:team_id/conversations/views/move_folder/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, string>
                    movePayloads.push(body)
                    // Mirror the server: rewrite the folder on the matched subtree
                    views = views.map((view) =>
                        view.folder === body.from_folder
                            ? { ...view, folder: body.to_folder }
                            : view.folder.startsWith(`${body.from_folder}/`)
                              ? {
                                    ...view,
                                    folder: [body.to_folder, view.folder.slice(body.from_folder.length + 1)]
                                        .filter(Boolean)
                                        .join('/'),
                                }
                              : view
                    )
                    return [200, { moved: 2, short_ids: ['parent', 'child'], to_folder: body.to_folder }]
                },
            },
            patch: {
                '/api/projects/:team_id/conversations/views/:short_id/': async ({ request, params }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    return [200, { ...makeView(params.short_id as string, ''), ...body }]
                },
            },
        })
        initKeaTests()
        logic = ticketViewsLogic({ id: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('moves a single view by patching its folder', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.moveViewToFolder('parent', 'Ops')
        }).toFinishAllListeners()

        expect(logic.values.views.find((view) => view.short_id === 'parent')?.folder).toEqual('Ops')
    })

    it('moves a folder and reloads so the server owns the resulting paths', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.moveFolder('Escalations', 'Ops/Escalations')
        }).toFinishAllListeners()

        expect(movePayloads).toEqual([{ from_folder: 'Escalations', to_folder: 'Ops/Escalations' }])
        expect(logic.values.views.map((view) => view.folder).sort()).toEqual(['Ops/Escalations', 'Ops/Escalations/EU'])
        expect(logic.values.movingFolders).toEqual([])
    })

    it('renames a folder in place, keeping its parent', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadViews()
        }).toFinishAllListeners()

        // Renaming a nested folder must not reparent it to the root
        await expectLogic(logic, () => {
            logic.actions.renameFolder('Escalations/EU', 'Europe')
        }).toFinishAllListeners()

        expect(movePayloads).toEqual([{ from_folder: 'Escalations/EU', to_folder: 'Escalations/Europe' }])
    })

    it('reloads views when a folder move fails', async () => {
        silenceKeaLoadersErrors()
        useMocks({
            get: { '/api/projects/:team_id/conversations/views/': () => [200, { results: views }] },
            post: { '/api/projects/:team_id/conversations/views/move_folder/': () => [404, { detail: 'gone' }] },
        })

        await expectLogic(logic, () => {
            logic.actions.moveFolder('Escalations', 'Ops')
        })
            .toFinishAllListeners()
            .toDispatchActions(['moveFolder', 'loadViews', 'moveFolderComplete'])

        expect(logic.values.movingFolders).toEqual([])
        resumeKeaLoadersErrors()
    })

    it('keeps expanded folders across a remount', async () => {
        logic.actions.toggleFolderExpanded(folderNodeId('Escalations'))
        expect(logic.values.expandedFolderIds).toEqual([folderNodeId('Escalations')])

        logic.unmount()
        logic = ticketViewsLogic({ id: 'test' })
        logic.mount()

        expect(logic.values.expandedFolderIds).toEqual([folderNodeId('Escalations')])
    })

    it('reveals a folder by expanding its whole ancestor chain', () => {
        logic.actions.revealFolder('Escalations/EU/Tier1')

        expect(logic.values.expandedFolderIds).toEqual([
            folderNodeId('Escalations'),
            folderNodeId('Escalations/EU'),
            folderNodeId('Escalations/EU/Tier1'),
        ])
    })
})
