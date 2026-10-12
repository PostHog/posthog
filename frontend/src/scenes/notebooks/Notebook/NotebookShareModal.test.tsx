import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { notebookLogic } from './notebookLogic'
import { NotebookShareModal } from './NotebookShareModal'

jest.mock('lib/components/Sharing/SharingModal', () => ({
    SHARING_MODAL_WIDTH: 640,
    SharingModalContent: () => null,
}))

describe('NotebookShareModal', () => {
    it('opens access control for the notebook shown over another page', async () => {
        const shortId = 'notebook-in-panel'
        initKeaTests()
        router.actions.push(urls.dashboards())
        const logic = notebookLogic({ shortId })
        logic.mount()
        logic.actions.openShareModal()
        render(<NotebookShareModal shortId={shortId} />)

        await userEvent.click(screen.getByRole('button', { name: 'Open access control' }))

        expect(router.values.location.pathname).toBe(urls.currentProject(urls.notebook(shortId)))
        expect(router.values.hashParams.panel).toBe(SidePanelTab.AccessControl)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.AccessControl)
        expect(logic.values.isShareModalOpen).toBe(false)
        logic.unmount()
    })
})
