import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { notebookLogic } from '../Notebook/notebookLogic'
import { notebookPanelLogic } from './notebookPanelLogic'

describe('notebookPanelLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:project_id/notebooks/missing-id/': () => [404, { detail: 'Not found.' }],
                '/api/projects/:project_id/notebooks/denied-id/': () => [
                    403,
                    { type: 'authentication_error', code: 'permission_denied', detail: 'No access.' },
                ],
                '/api/projects/:project_id/notebooks/flaky-id/': () => [500, { detail: 'Server error.' }],
            },
        })
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

    it.each([
        ['is not found', 'scratchpad', 'missing-id'],
        ['is not accessible', 'scratchpad', 'denied-id'],
        ['fails to load for another reason', 'flaky-id', 'flaky-id'],
    ])('when the selected notebook %s, the selection becomes %s', async (_, expectedSelection, shortId) => {
        notebookPanelLogic.actions.selectNotebook(shortId, { silent: true })
        const logic = notebookLogic({ shortId })
        logic.mount()

        await expectLogic(logic, () => logic.actions.loadNotebook()).toFinishAllListeners()

        expect(notebookPanelLogic.values.selectedNotebook).toEqual(expectedSelection)
        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
    })
})
