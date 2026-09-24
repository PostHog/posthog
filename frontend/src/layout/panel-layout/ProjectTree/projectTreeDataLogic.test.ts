import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from '../panelLayoutLogic'
import { customProductsLogic } from './customProductsLogic'
import { MovedItem, projectTreeDataLogic } from './projectTreeDataLogic'
import { projectTreeLogic } from './projectTreeLogic'

// pluralize() joins the count to the unit with a non-breaking space, which no reader can see in an assertion.
const toastText = (message: unknown): string => String(message).replace(/\u00a0/g, ' ')

describe('projectTreeDataLogic', () => {
    let logic: ReturnType<typeof projectTreeDataLogic.build>
    let unmount: () => void

    beforeEach(async () => {
        jest.restoreAllMocks()
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] })

        initKeaTests()
        panelLayoutLogic.mount()
        panelLayoutLogic.actions.clearActivePanelIdentifier()
        logic = projectTreeDataLogic()
        unmount = logic.mount()
        await expectLogic(logic).toDispatchActions(['loadFolderSuccess'])
        jest.clearAllMocks()
    })

    afterEach(() => {
        unmount?.()
        jest.restoreAllMocks()
    })

    it('initializes the home folder once when the sidebar flag arrives after mount', async () => {
        const initialize = jest.fn(() => [200, { id: 'home', path: 'Users/Alex' }])
        useMocks({ post: { '/api/projects/:team_id/file_system/home_folder/': initialize } })
        expect(logic.values.homeFolder).toBeNull()
        await expectLogic(logic, () => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIMPLE_SIDEPANEL], {
                [FEATURE_FLAGS.SIMPLE_SIDEPANEL]: true,
            })
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIMPLE_SIDEPANEL], {
                [FEATURE_FLAGS.SIMPLE_SIDEPANEL]: true,
            })
        }).toDispatchActions(['loadHomeFolderSuccess'])
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIMPLE_SIDEPANEL], {
            [FEATURE_FLAGS.SIMPLE_SIDEPANEL]: true,
        })
        expect(initialize).toHaveBeenCalledTimes(1)
        expect(logic.values.currentHomeFolder).toEqual({ id: 'home', path: 'Users/Alex' })
        logic.actions.loadFolderSuccess(
            'Research',
            [{ id: 'home', path: 'Research/My work', type: 'folder' }],
            false,
            0
        )
        expect(logic.values.currentHomeFolder?.path).toBe('Research/My work')
    })

    it.each(['loaded', 'loading', 'has-more', 'populated'] as const)(
        'renders a starred nested folder with %s contents',
        (state) => {
            const folder = 'Research/Ideas'
            logic.actions.loadShortcutsSuccess([{ id: 'star-folder', path: 'Ideas', type: 'folder', ref: folder }])
            logic.actions.loadFolderSuccess(
                folder,
                state === 'populated' ? [{ id: 'note', path: `${folder}/Notes`, type: 'notebook', ref: 'notes' }] : [],
                state === 'has-more',
                0
            )
            if (state === 'loading') {
                logic.actions.loadFolderStart(folder)
            }

            const [starredFolder] = logic.values.getShortcutTreeItems('', false)
            expect(starredFolder.id).toBe('shortcuts://Ideas')
            expect(starredFolder.children).toHaveLength(1)
            expect(starredFolder.children?.[0]).toMatchObject(
                state === 'loaded'
                    ? { name: 'Empty folder', type: 'empty-folder', disableSelect: true }
                    : state === 'loading'
                      ? { name: 'Loading...', type: 'loading-indicator' }
                      : state === 'has-more'
                        ? { name: 'Load more...' }
                        : { name: 'Notes', record: { path: `${folder}/Notes` } }
            )
        }
    )

    it('shows only the products the user added, with nothing injected alongside them', () => {
        customProductsLogic.actions.loadCustomProductsSuccess([
            {
                id: 'abc',
                product_path: 'Session replay',
                enabled: true,
                created_at: '2026-01-01T00:00:00Z',
                updated_at: '2026-01-01T00:00:00Z',
            },
        ])

        const paths = logic.values.getCustomProductTreeItems('').map((item) => item.record?.path)

        expect(paths).toEqual(['Session replay'])
    })

    it('handles null unfiled item responses', async () => {
        jest.mocked(api.fileSystem.unfiled).mockResolvedValueOnce(null)
        await expectLogic(logic, () => {
            logic.actions.loadUnfiledItems()
        })
            .toDispatchActions(['loadUnfiledItems', 'loadUnfiledItemsSuccess'])
            .toMatchValues({ unfiledItems: true })

        expect(api.fileSystem.list).not.toHaveBeenCalled()
    })

    it('reconciles unfiled items when the project tree becomes active', async () => {
        const rootlessTree = projectTreeLogic({ key: 'project-tree' })
        rootlessTree.mount()

        const projectTree = projectTreeLogic({ key: 'project-tree', root: 'project://', isActiveInPanel: true })

        await expectLogic(logic, () => {
            projectTree.mount()
        }).toDispatchActions(['loadUnfiledItems', 'loadUnfiledItemsSuccess'])

        projectTree.unmount()
        rootlessTree.unmount()
    })

    it('does not reconcile unfiled items when the project tree is hidden', () => {
        const projectTree = projectTreeLogic({ key: 'project-tree', root: 'project://', isActiveInPanel: false })

        projectTree.mount()

        expect(api.fileSystem.unfiled).not.toHaveBeenCalled()
        projectTree.unmount()
    })

    it('reconciles unfiled items when a non-panel project tree opens', async () => {
        const projectTree = projectTreeLogic({ key: 'folder-select', root: 'project://' })

        await expectLogic(logic, () => {
            projectTree.mount()
        }).toDispatchActions(['loadUnfiledItems', 'loadUnfiledItemsSuccess'])

        projectTree.unmount()
    })

    it('does not load Unfiled after the root folder loads in a hidden project tree', async () => {
        const projectTree = projectTreeLogic({ key: 'project-tree', root: 'project://', isActiveInPanel: false })
        projectTree.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.clearAllMocks()

        logic.actions.loadFolderSuccess('', [], false, 0)
        await expectLogic(logic).toFinishAllListeners()

        expect(api.fileSystem.list).not.toHaveBeenCalled()
        projectTree.unmount()
    })

    it('shares pending item lookups across tree mounts and navigation callbacks', async () => {
        jest.spyOn(breadcrumbsLogic.selectors, 'projectTreeRef').mockReturnValue({ type: 'insight', ref: 'insight1' })
        let resolveItem!: () => void
        jest.mocked(api.fileSystem.list).mockImplementation((params) =>
            params?.ref
                ? new Promise((resolve) => {
                      resolveItem = () =>
                          resolve({
                              count: 1,
                              users: [],
                              results: [{ id: 'file1', ref: 'insight1', type: 'insight', path: 'Reports/Insight' }],
                          })
                  })
                : Promise.resolve({ count: 0, results: [], users: [] })
        )
        const projectTree = projectTreeLogic({ key: 'project-tree', root: 'project://', isActiveInPanel: false })
        const pickerTree = projectTreeLogic({ key: 'folder-select', root: 'project://' })
        projectTree.mount()
        pickerTree.mount()
        projectTree.actions.assureVisibility({ type: 'insight', ref: 'insight1' }, false)
        expect(
            jest.mocked(api.fileSystem.list).mock.calls.filter(([params]) => params?.ref === 'insight1')
        ).toHaveLength(1)

        resolveItem()
        await expectLogic(projectTree).toFinishAllListeners()
        expect(logic.values.viableItems).toEqual(expect.arrayContaining([expect.objectContaining({ ref: 'insight1' })]))
        await expectLogic(projectTree, () => {
            projectTree.actions.assureVisibility({ type: 'insight', ref: 'insight1' }, false)
        }).toFinishAllListeners()
        expect(
            jest.mocked(api.fileSystem.list).mock.calls.filter(([params]) => params?.ref === 'insight1')
        ).toHaveLength(1)

        jest.mocked(api.fileSystem.list).mockResolvedValue({ count: 0, results: [], users: [] })
        await expectLogic(logic, () => logic.actions.syncTypeAndRef('insight', 'insight1')).toFinishAllListeners()
        expect(
            jest.mocked(api.fileSystem.list).mock.calls.filter(([params]) => params?.ref === 'insight1')
        ).toHaveLength(2)
        pickerTree.unmount()
        projectTree.unmount()
    })

    it('loads current insight metadata when a file consumer opens and follows navigation', async () => {
        const currentItem = jest
            .spyOn(projectTreeDataLogic.selectors, 'projectTreeRef')
            .mockReturnValue({ type: 'insight', ref: 'insight1' })
        const consumer = sceneFileLogic()
        consumer.mount()
        await expectLogic(consumer).toFinishAllListeners()
        expect(api.fileSystem.list).toHaveBeenCalledWith({ type: 'insight', ref: 'insight1' })
        currentItem.mockReturnValue({ type: 'insight', ref: 'insight2' })
        await expectLogic(consumer, () =>
            panelLayoutLogic.actions.setActivePanelIdentifier('Products')
        ).toFinishAllListeners()
        expect(api.fileSystem.list).toHaveBeenCalledWith({ type: 'insight', ref: 'insight2' })
        consumer.unmount()
    })

    it('defers ancestor folder loading until Files opens and follows the latest insight', async () => {
        const currentItem = jest.spyOn(breadcrumbsLogic.selectors, 'projectTreeRef').mockReturnValue({
            type: 'insight',
            ref: 'insight1',
        })
        jest.mocked(api.fileSystem.list).mockImplementation(async (params) => ({
            count: params?.ref ? 1 : 0,
            users: [],
            results: params?.ref
                ? [
                      {
                          id: String(params.ref),
                          ref: String(params.ref),
                          type: 'insight',
                          path: params.ref === 'insight1' ? 'Unfiled/Insights/First insight' : 'Reports/Latest insight',
                      },
                  ]
                : [],
        }))
        const projectTree = projectTreeLogic({ key: 'project-tree' })
        projectTree.mount()
        await expectLogic(projectTree).toFinishAllListeners()
        expect(api.fileSystem.list).not.toHaveBeenCalledWith(expect.objectContaining({ ref: 'insight1' }))
        expect(api.fileSystem.list).not.toHaveBeenCalledWith(expect.objectContaining({ parent: 'Unfiled/Insights' }))
        expect(logic.values.sortedItems).not.toEqual(
            expect.arrayContaining([expect.objectContaining({ ref: 'insight1' })])
        )

        currentItem.mockReturnValue({ type: 'insight', ref: 'insight2' })
        await expectLogic(projectTree, () => {
            panelLayoutLogic.actions.setActivePanelIdentifier('Products')
        }).toFinishAllListeners()
        expect(api.fileSystem.list).not.toHaveBeenCalledWith(expect.objectContaining({ parent: 'Reports' }))
        expect(api.fileSystem.list).not.toHaveBeenCalledWith(expect.objectContaining({ ref: 'insight2' }))

        await expectLogic(projectTree, () => {
            panelLayoutLogic.actions.setActivePanelIdentifier('Project')
        }).toFinishAllListeners()
        expect(api.fileSystem.list).toHaveBeenCalledWith({ parent: 'Reports', depth: 2, limit: 101, offset: 0 })
        expect(api.fileSystem.list).not.toHaveBeenCalledWith(expect.objectContaining({ parent: 'Unfiled/Insights' }))
        projectTree.unmount()
    })

    it.each(['already-open', 'folder-picker', 'explicit-reveal'] as const)(
        'loads ancestor folders for %s',
        async (mode) => {
            jest.spyOn(breadcrumbsLogic.selectors, 'projectTreeRef').mockReturnValue({
                type: 'insight',
                ref: 'insight1',
            })
            logic.actions.createSavedItem({
                id: 'file1',
                type: 'insight',
                ref: 'insight1',
                path: 'Unfiled/Insights/Insight',
            })
            if (mode === 'already-open') {
                panelLayoutLogic.mount()
                panelLayoutLogic.actions.setActivePanelIdentifier('Project')
            }
            const projectTree = projectTreeLogic({
                key: mode === 'folder-picker' ? 'folder-select' : 'project-tree',
                root: 'project://',
            })
            projectTree.mount()
            await expectLogic(projectTree).toFinishAllListeners()
            if (mode === 'explicit-reveal') {
                expect(api.fileSystem.list).not.toHaveBeenCalledWith(
                    expect.objectContaining({ parent: 'Unfiled/Insights' })
                )
                await expectLogic(projectTree, () => {
                    projectTree.actions.assureVisibility({ type: 'insight', ref: 'insight1' })
                }).toFinishAllListeners()
            }
            expect(api.fileSystem.list).toHaveBeenCalledWith({
                parent: 'Unfiled/Insights',
                depth: 3,
                limit: 101,
                offset: 0,
            })
            projectTree.unmount()
        }
    )

    it('loads unfiled folders when the count response reports items', async () => {
        logic.actions.createSavedItem({ id: 'saved-insight', path: 'Unfiled/Insights/Saved insight', type: 'insight' })
        jest.mocked(api.fileSystem.unfiled).mockResolvedValueOnce({ count: 1 })

        await expectLogic(logic, () => {
            logic.actions.loadUnfiledItems()
        }).toDispatchActions([
            'loadUnfiledItems',
            ({ type, payload }) => type === logic.actionTypes.loadFolder && payload.folder === 'Unfiled',
            ({ type, payload }) => type === logic.actionTypes.loadFolder && payload.folder === 'Unfiled/Insights',
            'loadUnfiledItemsSuccess',
        ])

        expect(api.fileSystem.list).toHaveBeenCalledWith({
            parent: 'Unfiled',
            depth: 2,
            limit: 101,
            offset: 0,
        })
        expect(api.fileSystem.list).toHaveBeenCalledWith({
            parent: 'Unfiled/Insights',
            depth: 3,
            limit: 101,
            offset: 0,
        })
    })

    it('reports a bulk move once, with an undo that reverts every item', async () => {
        const success = jest.spyOn(lemonToast, 'success').mockReturnValue('' as any)
        const move = jest.spyOn(api.fileSystem, 'move').mockResolvedValue({} as any)
        const items = [
            { id: 'fs-1', type: 'dashboard', path: 'Marketing/A', ref: '1' },
            { id: 'fs-2', type: 'dashboard', path: 'Marketing/B', ref: '2' },
            { id: 'fs-3', type: 'dashboard', path: 'Marketing/C', ref: '3' },
        ]

        await expectLogic(logic, () => {
            logic.actions.moveItems(
                items.map((item) => ({ item: item as any, newPath: `Product/${item.path.slice(-1)}` })),
                true,
                'test'
            )
        })
            // One announcement carrying everything that landed, so a consumer whose work is worth doing once
            // per operation (a refetch) reads the boundary off the action instead of inferring it from a timer.
            .toDispatchActions([
                ({ type, payload }) =>
                    type === logic.actionTypes.movesSettled &&
                    payload.moved.map(({ item }: MovedItem) => item.id).join() === 'fs-1,fs-2,fs-3',
            ])
            .toFinishAllListeners()

        expect(move).toHaveBeenCalledTimes(3)
        // movesSettled rides in the same branch as this toast, so one toast is one announcement.
        expect(success).toHaveBeenCalledTimes(1)
        expect(toastText(success.mock.calls[0][0])).toEqual('Moved 3 items')

        // Undo has to carry the whole batch: the per-item toast it replaced could only revert one item.
        move.mockClear()
        success.mock.calls[0][1]?.button?.action?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(move.mock.calls).toEqual([
            ['fs-1', 'Marketing/A'],
            ['fs-2', 'Marketing/B'],
            ['fs-3', 'Marketing/C'],
        ])
    })

    it('reports a partly failed bulk move as what moved plus what did not', async () => {
        const success = jest.spyOn(lemonToast, 'success').mockReturnValue('' as any)
        const error = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        jest.spyOn(api.fileSystem, 'move')
            .mockResolvedValueOnce({} as any)
            .mockRejectedValueOnce(new Error('nope'))
            .mockRejectedValueOnce(new Error('nope'))
        jest.spyOn(console, 'error').mockReturnValue()

        await expectLogic(logic, () => {
            logic.actions.moveItems(
                [
                    { item: { id: 'fs-1', type: 'dashboard', path: 'Marketing/A' } as any, newPath: 'Product/A' },
                    { item: { id: 'fs-2', type: 'dashboard', path: 'Marketing/B' } as any, newPath: 'Product/B' },
                    { item: { id: 'fs-3', type: 'dashboard', path: 'Marketing/C' } as any, newPath: 'Product/C' },
                ],
                true,
                'test'
            )
        }).toFinishAllListeners()

        expect(toastText(success.mock.calls[0][0])).toEqual('Moved 1 item')
        expect(toastText(error.mock.calls[0][0])).toEqual('Could not move 2 items. Try again.')

        // Undo may only revert what landed. Reverting a failed item would move it away from where it still is.
        const move = jest.mocked(api.fileSystem.move)
        move.mockClear().mockResolvedValue({} as any)
        success.mock.calls[0][1]?.button?.action?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(move.mock.calls).toEqual([['fs-1', 'Marketing/A']])
    })

    it('keeps the underlying error on a single failed move', async () => {
        const error = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
        jest.spyOn(api.fileSystem, 'move').mockRejectedValue(new Error('nope'))
        jest.spyOn(console, 'error').mockReturnValue()

        await expectLogic(logic, () => {
            logic.actions.moveItem(
                { id: 'fs-1', type: 'dashboard', path: 'Marketing/A' } as any,
                'Product/A',
                true,
                'test'
            )
        }).toFinishAllListeners()

        expect(error).toHaveBeenCalledWith('Error moving item: Error: nope')
    })

    it('deleteSavedItem does not crash when the parent folder is not loaded (lazy store)', () => {
        // Folders load lazily; deleting an item whose parent folder was never loaded must not throw on
        // state[folder].filter (previously "Cannot read properties of undefined (reading 'filter')").
        expect(() =>
            logic.actions.deleteSavedItem({ id: 'fs-x', type: 'dashboard', path: 'Marketing/Q1/X', ref: '9' } as any)
        ).not.toThrow()
    })
})
