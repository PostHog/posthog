import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useContext, useEffect } from 'react'

import { useComponentPanelState } from './componentPanelContext'
import { NotebookComponentRunStatusContext } from './componentRunStatus'
import { NotebookComponentToolbarExtrasContext } from './componentToolbarExtras'
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

    it('marks the block with the run status the host resolves for it', () => {
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: () => <div>Results</div>,
            },
        ])

        const { container } = render(
            <NotebookComponentRunStatusContext.Provider value={() => 'stale'}>
                <NotebookComponentShell
                    node={{
                        id: 'probe-node',
                        type: 'component',
                        tagName: 'Probe',
                        props: {},
                    }}
                    mode="edit"
                    componentPanels={{ filters: false, results: true }}
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
            </NotebookComponentRunStatusContext.Provider>
        )

        const shell = container.querySelector('.MarkdownNotebook__component-shell') as HTMLElement

        expect(shell.classList.contains('MarkdownNotebook__component-shell--status-stale')).toBe(true)
    })

    it('renders toolbar extras published by the component', async () => {
        const onAction = jest.fn()
        const onMenuItem = jest.fn()

        function ExtrasProbe(): JSX.Element {
            const setToolbarExtras = useContext(NotebookComponentToolbarExtrasContext)
            useEffect(() => {
                setToolbarExtras?.({
                    actions: [{ text: 'Add metric', onClick: onAction }],
                    menuItems: [{ label: 'Refresh', onClick: onMenuItem }],
                })
            }, [setToolbarExtras])
            return <div>Results</div>
        }

        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: ExtrasProbe,
            },
        ])

        const renderShell = (mode: 'edit' | 'view'): ReturnType<typeof render> =>
            render(
                <NotebookComponentShell
                    node={{
                        id: 'probe-node',
                        type: 'component',
                        tagName: 'Probe',
                        props: {},
                    }}
                    mode={mode}
                    componentPanels={{ filters: false, results: true }}
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

        const editRender = renderShell('edit')

        const actionButton = screen.getByText('Add metric')
        fireEvent.click(actionButton)
        expect(onAction).toHaveBeenCalled()

        await userEvent.click(screen.getByLabelText('More actions'))
        await userEvent.click(await screen.findByText('Refresh'))
        expect(onMenuItem).toHaveBeenCalled()

        editRender.unmount()

        // The menu still renders in view mode (e.g. profile canvases), the actions row does not.
        renderShell('view')
        expect(screen.queryByText('Add metric')).toBeNull()
        expect(screen.getByLabelText('More actions')).toBeTruthy()
    })
})
