import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenu, DropdownMenuContent } from 'lib/ui/DropdownMenu/DropdownMenu'
import { terminalDockLogic } from 'scenes/terminal/terminalDockLogic'

import { initKeaTests } from '~/test/init'

import { projectTreeDataLogic } from '../projectTreeDataLogic'
import { MenuItems } from './MenuItems'

describe('MenuItems', () => {
    let unmountLogic: () => void
    let unmountTerminalLogic: () => void

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIMPLE_SIDEPANEL], {})
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] })
        jest.spyOn(api.fileSystem, 'create').mockImplementation(async (item) => ({ ...item, id: 'new-folder' }))
        unmountLogic = projectTreeDataLogic.mount()
        unmountTerminalLogic = terminalDockLogic.mount()
    })

    afterEach(() => {
        cleanup()
        unmountLogic()
        unmountTerminalLogic()
        jest.restoreAllMocks()
    })

    it.each([
        ['project://', 'project://Research/Ideas', "Research/Alice's ideas", undefined, "Research/Alice's ideas"],
        ['shortcuts://', 'shortcuts://Ideas', 'Ideas', 'Research/Ideas', 'Research/Ideas'],
        ['project://', 'project-folder-empty/', '', undefined, ''],
    ])('opens the correct terminal folder from %s %s', async (root, id, path, ref, expectedFolder) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: true })
        terminalDockLogic.actions.setDockOpen(true)
        render(
            <DropdownMenu defaultOpen>
                <DropdownMenuContent>
                    <MenuItems
                        type="dropdown"
                        root={root}
                        item={{ id, name: 'Ideas', record: { path, ref, type: 'folder' } }}
                    />
                </DropdownMenuContent>
            </DropdownMenu>
        )
        fireEvent.click(await screen.findByText('Open in terminal'))
        expect(terminalDockLogic.values.requestedFolder).toBe(expectedFolder)
        expect(terminalDockLogic.values.dockOpen).toBe(true)
    })

    it.each([
        { enabled: true, dockOpen: false, route: '/', type: 'folder', root: 'project://', visible: false },
        { enabled: false, dockOpen: true, route: '/', type: 'folder', root: 'project://', visible: false },
        { enabled: true, dockOpen: true, route: '/', type: 'notebook', root: 'project://', visible: false },
        { enabled: true, dockOpen: true, route: '/', type: 'folder', root: 'products://', visible: false },
        {
            enabled: true,
            dockOpen: false,
            route: '/project/42/terminal',
            type: 'folder',
            root: 'project://',
            visible: true,
        },
    ])(
        'shows the folder action only for a visible terminal: %j',
        async ({ enabled, dockOpen, route, type, root, visible }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.POSTHOG_TERMINAL]: enabled })
            terminalDockLogic.actions.setDockOpen(dockOpen)
            router.actions.push(route)
            render(
                <DropdownMenu defaultOpen>
                    <DropdownMenuContent>
                        <MenuItems
                            type="dropdown"
                            root={root}
                            item={{ id: `${root}Ideas`, name: 'Ideas', record: { path: 'Ideas', type } }}
                        />
                    </DropdownMenuContent>
                </DropdownMenu>
            )
            await screen.findByRole('menu')
            expect(screen.queryByText('Open in terminal') !== null).toBe(visible)
        }
    )

    it.each(['context', 'dropdown'] as const)(
        'creates folders and resources in the original starred folder through the %s menu',
        async (type) => {
            const menu = (
                <MenuItems
                    type={type}
                    root="shortcuts://"
                    item={{
                        id: 'shortcuts://Ideas',
                        name: 'Ideas',
                        record: { id: 'star-folder', path: 'Ideas', type: 'folder', ref: 'Research/Ideas' },
                    }}
                />
            )
            const { unmount } = render(
                type === 'context' ? (
                    <ContextMenu>
                        <ContextMenuTrigger>Ideas</ContextMenuTrigger>
                        <ContextMenuContent>{menu}</ContextMenuContent>
                    </ContextMenu>
                ) : (
                    <DropdownMenu defaultOpen>
                        <DropdownMenuContent>{menu}</DropdownMenuContent>
                    </DropdownMenu>
                )
            )
            if (type === 'context') {
                fireEvent.contextMenu(screen.getByText('Ideas'))
            }
            fireEvent.keyDown(await screen.findByText('New...'), { key: 'ArrowRight' })
            fireEvent.click(await screen.findByText('Folder'))
            await waitFor(() =>
                expect(api.fileSystem.create).toHaveBeenCalledWith(
                    expect.objectContaining({ path: 'Research/Ideas/Untitled folder', type: 'folder' })
                )
            )
            unmount()

            render(
                type === 'context' ? (
                    <ContextMenu>
                        <ContextMenuTrigger>Ideas</ContextMenuTrigger>
                        <ContextMenuContent>{menu}</ContextMenuContent>
                    </ContextMenu>
                ) : (
                    <DropdownMenu defaultOpen>
                        <DropdownMenuContent>{menu}</DropdownMenuContent>
                    </DropdownMenu>
                )
            )
            if (type === 'context') {
                fireEvent.contextMenu(screen.getByText('Ideas'))
            }
            fireEvent.keyDown(await screen.findByText('New...'), { key: 'ArrowRight' })
            fireEvent.click(await screen.findByText('New dashboard'))
            expect(projectTreeDataLogic.values.lastNewFolder).toBe('Research/Ideas')
        }
    )
})
