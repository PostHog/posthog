import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenu, DropdownMenuContent } from 'lib/ui/DropdownMenu/DropdownMenu'

import { initKeaTests } from '~/test/init'

import { projectTreeDataLogic } from '../projectTreeDataLogic'
import { MenuItems } from './MenuItems'

describe('MenuItems', () => {
    let unmountLogic: () => void

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SIMPLE_SIDEPANEL], {})
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] })
        jest.spyOn(api.fileSystem, 'create').mockImplementation(async (item) => ({ ...item, id: 'new-folder' }))
        unmountLogic = projectTreeDataLogic.mount()
    })

    afterEach(() => {
        cleanup()
        unmountLogic()
        jest.restoreAllMocks()
    })

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
