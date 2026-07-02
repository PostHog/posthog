import { getNotebookSqlOutputToolbarVisibility } from './NotebookNodeQuery'

describe('NotebookNodeQuery', () => {
    const markdownPanelState = ({
        filters,
        results,
    }: {
        filters: boolean
        results: boolean
    }): NonNullable<Parameters<typeof getNotebookSqlOutputToolbarVisibility>[0]['componentPanelState']> => ({
        componentPanels: { filters, results },
        showEditPanel: filters,
        showViewPanel: results,
    })

    it('shows SQL output tabs only when markdown edit and view panels are both open', () => {
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: true, results: true }),
                expanded: false,
                isEditing: false,
            })
        ).toBe(true)

        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: true, results: false }),
                expanded: true,
                isEditing: true,
            })
        ).toBe(false)

        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: false, results: true }),
                expanded: true,
                isEditing: true,
            })
        ).toBe(false)

        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: markdownPanelState({ filters: false, results: false }),
                expanded: true,
                isEditing: true,
            })
        ).toBe(false)
    })

    it('falls back to legacy expanded and editing state outside markdown notebooks', () => {
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: null,
                expanded: true,
                isEditing: true,
            })
        ).toBe(true)
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: null,
                expanded: true,
                isEditing: false,
            })
        ).toBe(false)
        expect(
            getNotebookSqlOutputToolbarVisibility({
                componentPanelState: null,
                expanded: false,
                isEditing: true,
            })
        ).toBe(false)
    })
})
