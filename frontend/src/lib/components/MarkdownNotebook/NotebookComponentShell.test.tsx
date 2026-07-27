import { fireEvent, render, screen } from '@testing-library/react'

import { useComponentPanelState } from './componentPanelContext'
import { NotebookComponentShell } from './NotebookComponentShell'
import { createMarkdownNotebookRegistry } from './registry'

function PanelStateProbe(): JSX.Element {
    const panelState = useComponentPanelState()

    return (
        <div data-attr="panel-state">
            {panelState?.showEditPanel ? 'edit-open' : 'edit-closed'}{' '}
            {panelState?.showViewPanel ? 'view-open' : 'view-closed'}
        </div>
    )
}

describe('NotebookComponentShell', () => {
    it('provides markdown component panel state to rendered components', () => {
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: PanelStateProbe,
                EditComponent: () => <div>Edit panel</div>,
            },
        ])

        render(
            <NotebookComponentShell
                node={{
                    id: 'probe-node',
                    type: 'component',
                    tagName: 'Probe',
                    props: {},
                }}
                mode="edit"
                componentPanels={{ filters: true, results: true }}
                persistComponentPanelVisibility={false}
                isSelected={false}
                registry={registry}
                toggleComponentPanel={jest.fn()}
                setLocalComponentPanels={jest.fn()}
                rememberComponentPanels={jest.fn()}
                setBlockRef={jest.fn()}
                updateNode={jest.fn()}
                deleteNode={jest.fn()}
                deleteSelectedNotebookBlocks={jest.fn(() => false)}
                insertParagraphAfterNode={jest.fn()}
                moveFocusToAdjacentNode={jest.fn(() => false)}
            />
        )

        expect(screen.getByTestId('panel-state').textContent).toBe('edit-open view-open')
    })

    it('prevents toolbar mouse down from changing notebook selection before toggling panels', () => {
        const toggleComponentPanel = jest.fn()
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: PanelStateProbe,
                EditComponent: () => <div>Edit panel</div>,
            },
        ])

        const { container } = render(
            <NotebookComponentShell
                node={{
                    id: 'probe-node',
                    type: 'component',
                    tagName: 'Probe',
                    props: {},
                }}
                mode="edit"
                componentPanels={{ filters: true, results: true }}
                persistComponentPanelVisibility={false}
                isSelected={false}
                registry={registry}
                toggleComponentPanel={toggleComponentPanel}
                setLocalComponentPanels={jest.fn()}
                rememberComponentPanels={jest.fn()}
                setBlockRef={jest.fn()}
                updateNode={jest.fn()}
                deleteNode={jest.fn()}
                deleteSelectedNotebookBlocks={jest.fn(() => false)}
                insertParagraphAfterNode={jest.fn()}
                moveFocusToAdjacentNode={jest.fn(() => false)}
            />
        )

        const filtersButton = container.querySelector('button[aria-label="Hide filters"]') as HTMLButtonElement

        expect(fireEvent.mouseDown(filtersButton)).toBe(false)

        fireEvent.click(filtersButton)

        expect(toggleComponentPanel).toHaveBeenCalledWith('filters')
    })
})
