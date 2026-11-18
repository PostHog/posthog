import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'

import { biEditorLogic } from '../biEditorLogic'
import { BIEditorView, DEFAULT_BI_CONFIG, getBIShelfEditorKey } from '../biEditorTypes'
import { BIFilterPill } from './BIFilterPill'

describe('BIFilterPill', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each(['Remove filter', 'Done'])('only discards the empty filter when clicking %s', (button) => {
        const props = { tabId: 'empty-filter-removal' }
        const logic = biEditorLogic(props)
        const unmount = logic.mount()
        const field = { id: 'empty', name: '', expression: '', type: 'string' as const, source: { table: 'events' } }
        const nextFilter = {
            field: { ...field, id: 'event', name: 'event', expression: 'event' },
            operator: 'is_set' as const,
            value: '',
        }
        logic.actions.setAutoUpdate(false)
        logic.actions.restoreState({
            editorView: BIEditorView.BI,
            config: {
                ...DEFAULT_BI_CONFIG,
                source: field.source,
                filters: [{ field, operator: 'is_set', value: '' }, nextFilter],
            },
        })
        logic.actions.setActiveExpressionEditorId(getBIShelfEditorKey('filters', field.id))
        try {
            render(
                <BindLogic logic={biEditorLogic} props={props}>
                    <BIFilterPill index={0} />
                </BindLogic>
            )
            fireEvent.click(screen.getByText(button))
            expect(logic.values.config.filters).toEqual([nextFilter])
            expect(logic.values.activeExpressionEditorId).toBeNull()
        } finally {
            cleanup()
            unmount()
        }
    })
})
