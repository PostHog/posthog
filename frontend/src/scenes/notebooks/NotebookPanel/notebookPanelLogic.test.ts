import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { buildMarkdownNotebookContent } from '../Notebook/markdownNotebookV2'
import { NOTEBOOKS_VERSION } from '../Notebook/migrations/notebooksVersion'
import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookTarget } from '../types'
import { notebookPanelLogic } from './notebookPanelLogic'

describe('notebookPanelLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        notebookPanelLogic.mount()
    })

    it.each([undefined, 'notebook'] as const)(
        'shares persisted scratchpad content when mounting mode %s first',
        (mode) => {
            const shortId = 'scratchpad'
            const content = buildMarkdownNotebookContent('Notes from before the store key normalization')
            const storageKey = `${NOTEBOOKS_VERSION}.scenes.notebooks.Notebook.notebookLogic.scratchpad-undefined.localContent`
            localStorage.setItem(storageKey, JSON.stringify(content))
            const panelNotebook = notebookLogic({ shortId, mode, target: NotebookTarget.Popover })
            const unmount = panelNotebook.mount()
            try {
                const explicitNotebook = notebookLogic({ shortId, mode: 'notebook' })
                expect(explicitNotebook.values.mode).toBe('notebook')
                expect(explicitNotebook).toBe(panelNotebook)
                expect(explicitNotebook.values.localContent).toEqual(content)
                expect(notebookLogic({ shortId })).toBe(panelNotebook)
                const updatedContent = buildMarkdownNotebookContent('Updated scratchpad notes')
                explicitNotebook.actions.setLocalContent(updatedContent)
                expect(JSON.parse(localStorage.getItem(storageKey)!)).toEqual(updatedContent)
                expect(notebookLogic({ shortId, mode: 'canvas' })).not.toBe(panelNotebook)
            } finally {
                unmount()
            }
        }
    )

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
})
