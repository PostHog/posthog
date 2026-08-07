import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { notebookLogic } from '../Notebook/notebookLogic'
import { notebookPanelLogic } from './notebookPanelLogic'

describe('notebookPanelLogic', () => {
    beforeEach(() => {
        initKeaTests()
        notebookPanelLogic.mount()
    })

    it('keeps the side panel state unchanged while dragging notebook resources', async () => {
        notebookPanelLogic.actions.startDropMode()
        window.dispatchEvent(new MouseEvent('drag', { clientX: window.innerWidth - 10 }))

        await expectLogic(sidePanelStateLogic).toMatchValues({ sidePanelOpen: false, selectedTab: null })

        notebookPanelLogic.actions.endDropMode()
        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Notebooks)
        notebookPanelLogic.actions.startDropMode()
        window.dispatchEvent(new MouseEvent('drag', { clientX: window.innerWidth - 10 }))

        await expectLogic(notebookPanelLogic).toMatchValues({ dropMode: true })
        await expectLogic(sidePanelStateLogic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Notebooks,
        })

        notebookPanelLogic.actions.endDropMode()

        await expectLogic(notebookPanelLogic).toMatchValues({ dropMode: false })
        await expectLogic(sidePanelStateLogic).toMatchValues({
            sidePanelOpen: true,
            selectedTab: SidePanelTab.Notebooks,
        })
    })

    it('falls back to the scratchpad when the selected notebook 404s', async () => {
        useMocks({
            get: {
                '/api/projects/:project_id/notebooks/missing-notebook/': () => [404, { detail: 'Not found.' }],
            },
        })

        notebookPanelLogic.actions.selectNotebook('missing-notebook', { silent: true })
        await expectLogic(notebookPanelLogic).toMatchValues({ selectedNotebook: 'missing-notebook' })

        const logic = notebookLogic({ shortId: 'missing-notebook' })
        logic.mount()
        logic.actions.loadNotebook()

        await expectLogic(logic).toDispatchActions(['loadNotebookSuccess'])
        await expectLogic(notebookPanelLogic).toMatchValues({ selectedNotebook: 'scratchpad' })

        logic.unmount()
    })
})
