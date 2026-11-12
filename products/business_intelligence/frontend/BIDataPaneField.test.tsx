import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { BIField } from '~/queries/schema/schema-business-intelligence'
import { initKeaTests } from '~/test/init'

import { BIDataPaneField } from './BIDataPaneField'
import { biEditorLogic } from './biEditorLogic'
import { BIEditorView, DEFAULT_BI_CONFIG } from './biEditorTypes'

describe('BI data pane fields', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each(['click', 'dblClick', 'keyboard'] as const)('adds a field once on %s', async (interaction) => {
        const props = { tabId: 'field-selection' }
        const logic = biEditorLogic(props)
        const unmount = logic.mount()
        const field: BIField = {
            id: 'region',
            name: 'Region',
            expression: 'region',
            type: 'string',
            source: { table: 'example_orders' },
        }
        try {
            logic.actions.setAutoUpdate(false)
            logic.actions.restoreState({
                editorView: BIEditorView.BI,
                config: { ...DEFAULT_BI_CONFIG, source: field.source },
            })
            const addField = jest.spyOn(logic.actions, 'addFieldToShelf')
            render(
                <BindLogic logic={biEditorLogic} props={props}>
                    <BIDataPaneField field={field} measure={false} />
                </BindLogic>
            )
            const button = screen.getByTestId('bi-editor-data-pane-dimension')
            if (interaction === 'keyboard') {
                button.focus()
                await userEvent.keyboard('{Enter}')
            } else {
                await userEvent[interaction](button)
            }
            expect(logic.values.config.rows).toEqual([field])
            expect(addField).toHaveBeenCalledTimes(1)
        } finally {
            cleanup()
            unmount()
        }
    })
})
