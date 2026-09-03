import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useContext, useEffect, useMemo } from 'react'

import { useComponentPanelState } from './componentPanelContext'
import { NotebookComponentRunStatusContext } from './componentRunStatus'
import { NotebookComponentToolbarExtrasContext } from './componentToolbarExtras'
import { NotebookComponentShell } from './NotebookComponentShell'
import { createMarkdownNotebookRegistry } from './registry'
import { NotebookComponentRenderProps } from './types'

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
                    actions: [
                        {
                            text: 'Add metric',
                            icon: <span data-testid="action-menu-icon" />,
                            onClick: onAction,
                        },
                    ],
                    menuItems: [
                        {
                            label: 'Refresh',
                            sideIcon: <span data-testid="custom-menu-icon" />,
                            onClick: onMenuItem,
                        },
                    ],
                    editMenuItems: [{ label: 'Change view', items: [{ label: 'Summary', onClick: jest.fn() }] }],
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

        await userEvent.click(screen.getByLabelText('More actions'))
        expect(screen.queryByTestId('action-menu-icon')).toBeNull()
        await userEvent.click(await screen.findByText('Add metric'))
        expect(onAction).toHaveBeenCalled()

        await userEvent.click(screen.getByLabelText('More actions'))
        expect(screen.queryByTestId('custom-menu-icon')).toBeNull()
        await userEvent.click(await screen.findByText('Refresh'))
        expect(onMenuItem).toHaveBeenCalled()

        await userEvent.click(screen.getByLabelText('More actions'))
        expect(await screen.findByText('Change view')).toBeTruthy()

        editRender.unmount()

        // The menu still renders in view mode (e.g. profile canvases), but editing actions do not.
        const viewRender = renderShell('view')
        expect(screen.queryByText('Add metric')).toBeNull()
        expect(screen.getByLabelText('More actions')).toBeTruthy()
        await userEvent.click(screen.getByLabelText('More actions'))
        expect(screen.queryByText('Change view')).toBeNull()
        expect(screen.getByText('Refresh')).toBeTruthy()
        viewRender.unmount()
    })

    it('settles when a component publishes a menu derived from updateProps', async () => {
        function ViewMenuProbe({ updateProps }: NotebookComponentRenderProps): JSX.Element {
            const setToolbarExtras = useContext(NotebookComponentToolbarExtrasContext)
            const editMenuItems = useMemo(
                () => [
                    {
                        label: 'Change view',
                        items: [{ label: 'Summary', onClick: () => updateProps({ view: 'summary' }) }],
                    },
                ],
                [updateProps]
            )

            useEffect(() => {
                setToolbarExtras?.({ actions: [], menuItems: null, editMenuItems })
            }, [editMenuItems, setToolbarExtras])

            return <div>Results</div>
        }

        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: ViewMenuProbe,
            },
        ])

        const rendered = render(
            <NotebookComponentShell
                node={{ id: 'probe-node', type: 'component', tagName: 'Probe', props: {} }}
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
        )

        expect(within(rendered.container).getByText('Results')).toBeTruthy()
        await userEvent.click(within(rendered.container).getByLabelText('More actions'))
        expect(await screen.findByText('Change view')).toBeTruthy()
        rendered.unmount()
    })

    it('puts current-tab and new-tab resource links first in the overflow menu', async () => {
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Feature flag',
                category: 'Test',
                ViewComponent: () => <div>Results</div>,
                getHref: () => '/project/1/feature_flags/123',
            },
        ])

        render(
            <NotebookComponentShell
                node={{ id: 'probe-node', type: 'component', tagName: 'Probe', props: {} }}
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
        )

        expect(screen.queryByLabelText('Open in new tab')).toBeNull()
        await userEvent.click(screen.getByLabelText('More actions'))

        const menuItems = screen.getAllByRole('menuitem')
        expect(menuItems[0].textContent).toContain('Open feature flag')
        expect(menuItems[0].closest('a')?.getAttribute('target')).toBeNull()
        expect(menuItems[1].textContent).toContain('Open in new tab')
        expect(menuItems[1].closest('a')?.getAttribute('target')).toBe('_blank')
    })

    it('renders a published fixed title and status without offering title editing', () => {
        const toggleStatus = jest.fn()

        function FixedTitleProbe(): JSX.Element {
            const setToolbarExtras = useContext(NotebookComponentToolbarExtrasContext)
            useEffect(() => {
                setToolbarExtras?.({
                    actions: [],
                    menuItems: null,
                    title: 'onboarding-wizard-sync-mode',
                    titleStatus: {
                        label: 'Enabled',
                        type: 'success',
                        onClick: toggleStatus,
                    },
                })
            }, [setToolbarExtras])
            return <div>Release conditions</div>
        }

        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'FeatureFlagProbe',
                label: 'Feature flag',
                category: 'Test',
                editableTitle: false,
                ViewComponent: FixedTitleProbe,
            },
        ])

        const { container } = render(
            <NotebookComponentShell
                node={{
                    id: 'feature-flag-node',
                    type: 'component',
                    tagName: 'FeatureFlagProbe',
                    props: { title: 'Ignored custom title' },
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
        )

        const titleButton = container.querySelector(
            '.MarkdownNotebook__component-toolbar-title--button'
        ) as HTMLButtonElement
        expect(titleButton.textContent).toBe('onboarding-wizard-sync-mode')
        expect(screen.getByText('Enabled').closest('.LemonTag')?.classList.contains('LemonTag--success')).toBe(true)

        fireEvent.doubleClick(titleButton)
        expect(container.querySelector('.MarkdownNotebook__component-toolbar-title--input')).toBeNull()

        fireEvent.click(screen.getByText('Enabled'))
        expect(toggleStatus).toHaveBeenCalledTimes(1)
    })

    it('shows the filters toggle in view mode only when the host and definition opt in', () => {
        const toggleComponentPanel = jest.fn()
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: () => <div>Results</div>,
                EditComponent: () => <div>Filters panel</div>,
                viewModeFilters: true,
            },
        ])

        const renderShell = (allowViewModeFilters: boolean, filtersOpen: boolean): ReturnType<typeof render> =>
            render(
                <NotebookComponentShell
                    node={{
                        id: 'probe-node',
                        type: 'component',
                        tagName: 'Probe',
                        props: {},
                    }}
                    mode="view"
                    componentPanels={{ filters: filtersOpen, results: true }}
                    persistComponentPanelVisibility={false}
                    allowViewModeFilters={allowViewModeFilters}
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

        // Without the host opt-in (regular read-only notebooks) the toggle stays hidden.
        const withoutOptIn = renderShell(false, false)
        expect(within(withoutOptIn.container).queryByLabelText('Show filters')).toBeNull()
        withoutOptIn.unmount()

        const closedFilters = renderShell(true, false)
        fireEvent.click(within(closedFilters.container).getByLabelText('Show filters'))
        expect(toggleComponentPanel).toHaveBeenCalledWith('filters')
        expect(within(closedFilters.container).queryByText('Filters panel')).toBeNull()
        // The results visibility toggle stays edit-only: results always render in view mode.
        expect(within(closedFilters.container).queryByLabelText('Hide results')).toBeNull()
        closedFilters.unmount()

        const openFilters = renderShell(true, true)
        expect(within(openFilters.container).getByText('Filters panel')).toBeTruthy()
        expect(within(openFilters.container).getByText('Results')).toBeTruthy()
    })

    it('disables the filters toggle when the component publishes a disabled reason', () => {
        const toggleComponentPanel = jest.fn()

        function ExtrasProbe(): JSX.Element {
            const setToolbarExtras = useContext(NotebookComponentToolbarExtrasContext)
            useEffect(() => {
                setToolbarExtras?.({
                    actions: [],
                    menuItems: null,
                    filtersDisabledReason: 'Create a journey to configure this panel',
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
                EditComponent: () => <div>Filters panel</div>,
                viewModeFilters: true,
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
                mode="view"
                componentPanels={{ filters: false, results: true }}
                persistComponentPanelVisibility={false}
                allowViewModeFilters={true}
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

        const filtersButton = within(container).getByLabelText('Show filters')
        expect(filtersButton.getAttribute('aria-disabled')).toBe('true')
        fireEvent.click(filtersButton)
        expect(toggleComponentPanel).not.toHaveBeenCalled()
    })

    it('collapses output on read-only canvases', () => {
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: () => <div>Results</div>,
            },
        ])

        const renderShell = (
            allowViewModeFilters: boolean,
            componentPanels: { filters: boolean; results: boolean }
        ): ReturnType<typeof render> =>
            render(
                <NotebookComponentShell
                    node={{
                        id: 'probe-node',
                        type: 'component',
                        tagName: 'Probe',
                        props: {},
                    }}
                    mode="view"
                    componentPanels={componentPanels}
                    persistComponentPanelVisibility={false}
                    allowViewModeFilters={allowViewModeFilters}
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

        // Plain view mode ignores a collapsed results panel and offers no collapse toggle.
        const plainView = renderShell(false, { filters: false, results: false })
        expect(within(plainView.container).getByText('Results')).toBeTruthy()
        expect(within(plainView.container).queryByLabelText('Collapse')).toBeNull()
        plainView.unmount()

        const expandedCanvas = renderShell(true, { filters: false, results: true })
        expect(within(expandedCanvas.container).getByText('Results')).toBeTruthy()
        expect(within(expandedCanvas.container).getByLabelText('Collapse')).toBeTruthy()
        expandedCanvas.unmount()

        const collapsedCanvas = renderShell(true, { filters: false, results: false })
        expect(within(collapsedCanvas.container).queryByText('Results')).toBeNull()
        expect(within(collapsedCanvas.container).getByLabelText('Expand')).toBeTruthy()
    })

    it.each([
        ['edit', { filters: true, results: true }],
        ['view', { filters: false, results: true }],
        // Collapsed: the reason the control is a shell slot rather than a published toolbar extra —
        // a code cell stays runnable with neither its editor nor its results on screen.
        ['edit', { filters: false, results: false }],
    ] as const)('renders the definition toolbar control in %s mode with panels %p', (mode, componentPanels) => {
        const registry = createMarkdownNotebookRegistry([
            {
                tagName: 'Probe',
                label: 'Probe',
                category: 'Test',
                ViewComponent: () => <div>Results</div>,
                EditComponent: () => <div>Filters panel</div>,
                ToolbarComponent: () => <button type="button">Run</button>,
            },
        ])

        const { container } = render(
            <NotebookComponentShell
                node={{ id: 'probe-node', type: 'component', tagName: 'Probe', props: {} }}
                mode={mode}
                componentPanels={componentPanels}
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

        expect(
            within(container.querySelector('.MarkdownNotebook__component-toolbar') as HTMLElement).getByText('Run')
        ).toBeTruthy()
    })

    it('keeps the toolbar menu when collapsing unmounts the component', () => {
        function ExtrasProbe(): JSX.Element {
            const setToolbarExtras = useContext(NotebookComponentToolbarExtrasContext)
            useEffect(() => {
                setToolbarExtras?.({ actions: [], menuItems: [{ label: 'Refresh', onClick: jest.fn() }] })
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

        const buildShell = (componentPanels: { filters: boolean; results: boolean }): JSX.Element => (
            <NotebookComponentShell
                node={{
                    id: 'probe-node',
                    type: 'component',
                    tagName: 'Probe',
                    props: {},
                }}
                mode="edit"
                componentPanels={componentPanels}
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

        const { container, rerender } = render(buildShell({ filters: false, results: true }))
        expect(within(container).getByLabelText('More actions')).toBeTruthy()

        rerender(buildShell({ filters: false, results: false }))
        expect(within(container).queryByText('Results')).toBeNull()
        expect(within(container).getByLabelText('More actions')).toBeTruthy()
    })
})
