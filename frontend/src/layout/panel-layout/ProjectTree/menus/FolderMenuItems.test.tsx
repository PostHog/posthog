import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ContextMenu, ContextMenuContent, ContextMenuTrigger } from 'lib/ui/ContextMenu/ContextMenu'
import { DropdownMenu, DropdownMenuContent } from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { projectTreeDataLogic } from '../projectTreeDataLogic'
import { MenuItems } from './MenuItems'

describe('folder open menus', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SIMPLE_SIDEPANEL]: true })
        jest.spyOn(api.fileSystem, 'list').mockResolvedValue({ count: 0, results: [], users: [] })
        jest.spyOn(api.fileSystem, 'unfiled').mockResolvedValue(null)
        jest.spyOn(api.fileSystemShortcuts, 'list').mockResolvedValue({ count: 0, results: [] })
        projectTreeDataLogic.mount()
        panelLayoutLogic.mount()
    })
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each(['context', 'dropdown'] as const)('opens the original starred folder from the %s menu', async (type) => {
        const push = jest.spyOn(router.actions, 'push')
        const menu = (
            <MenuItems
                type={type}
                root="shortcuts://"
                item={{
                    id: 'shortcuts://Ideas',
                    name: 'Ideas',
                    record: { path: 'Ideas', type: 'folder', ref: 'Research/Ideas' },
                }}
            />
        )
        const showMenu = (): void => {
            render(
                type === 'context' ? (
                    <ContextMenu>
                        <ContextMenuTrigger>Folder trigger</ContextMenuTrigger>
                        <ContextMenuContent>{menu}</ContextMenuContent>
                    </ContextMenu>
                ) : (
                    <DropdownMenu defaultOpen>
                        <DropdownMenuContent>{menu}</DropdownMenuContent>
                    </DropdownMenu>
                )
            )
            if (type === 'context') {
                fireEvent.contextMenu(screen.getByText('Folder trigger'))
            }
        }
        panelLayoutLogic.actions.toggleLayoutNavCollapsed(true)
        showMenu()
        fireEvent.click(await screen.findByText('Open in sidebar'))
        expect(panelLayoutLogic.values.filesFolder).toBe('Research/Ideas')
        expect(panelLayoutLogic.values.navExperimentActiveTab).toBe('files')
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)
        cleanup()
        showMenu()
        fireEvent.click(await screen.findByText('Open in Files'))
        expect(push).toHaveBeenLastCalledWith(urls.projectFiles('Research/Ideas'))
    })
})
