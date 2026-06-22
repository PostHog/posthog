import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FilterPicker } from './FilterPicker'
import { FilterPickerNode } from './FilterPicker.types'

const valueNode: FilterPickerNode = { id: 'value', label: 'Active', kind: 'action' }
const operatorNode: FilterPickerNode = {
    id: 'operator',
    label: 'Equals',
    kind: 'branch',
    searchPlaceholder: 'Search values…',
    getChildren: () => ({ nodes: [valueNode], isLoading: false }),
}
const propertyNode: FilterPickerNode = {
    id: 'property',
    label: 'Status',
    kind: 'branch',
    searchPlaceholder: 'Choose an operator…',
    getChildren: () => ({ nodes: [operatorNode], isLoading: false }),
}

const renderPicker = (open: boolean): ReturnType<typeof render> =>
    render(
        <FilterPicker
            rootNodes={[propertyNode]}
            trigger={<button type="button">Add filter</button>}
            open={open}
            initialPath={{ nodeIds: ['property', 'operator'] }}
        />
    )

describe('FilterPicker', () => {
    afterEach(() => {
        cleanup()
    })

    it('re-applies initialPath after an open/close/open cycle', async () => {
        const { rerender } = renderPicker(true)

        expect(await screen.findByPlaceholderText('Search values…')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Active' })).toBeInTheDocument()

        rerender(
            <FilterPicker
                rootNodes={[propertyNode]}
                trigger={<button type="button">Add filter</button>}
                open={false}
                initialPath={{ nodeIds: ['property', 'operator'] }}
            />
        )
        rerender(
            <FilterPicker
                rootNodes={[propertyNode]}
                trigger={<button type="button">Add filter</button>}
                open={true}
                initialPath={{ nodeIds: ['property', 'operator'] }}
            />
        )

        expect(await screen.findByPlaceholderText('Search values…')).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Active' })).toBeInTheDocument()
    })

    it('loads content only for the active node, never for resolved ancestors', async () => {
        const propertyLoadContent = jest.fn()
        const operatorLoadContent = jest.fn()
        const operator: FilterPickerNode = {
            id: 'operator',
            label: 'Equals',
            kind: 'branch',
            searchPlaceholder: 'Search values…',
            getChildren: () => ({ nodes: [valueNode], isLoading: false }),
            loadContent: operatorLoadContent,
        }
        const property: FilterPickerNode = {
            id: 'property',
            label: 'Status',
            kind: 'branch',
            getChildren: () => ({ nodes: [operator], isLoading: false }),
            loadContent: propertyLoadContent,
        }

        render(
            <FilterPicker
                rootNodes={[property]}
                trigger={<button type="button">Add filter</button>}
                open={true}
                initialPath={{ nodeIds: ['property', 'operator'] }}
            />
        )

        expect(await screen.findByPlaceholderText('Search values…')).toBeInTheDocument()
        // The active node's content loads; the resolved ancestor's loadContent must not fire as a side effect.
        expect(operatorLoadContent).toHaveBeenCalled()
        expect(propertyLoadContent).not.toHaveBeenCalled()
    })

    it('back button on the value level returns to the operator level', async () => {
        renderPicker(true)

        expect(await screen.findByRole('button', { name: 'Active' })).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Go back to previous filter level' }))

        expect(await screen.findByRole('button', { name: 'Equals' })).toBeInTheDocument()
        expect(screen.queryByRole('button', { name: 'Active' })).not.toBeInTheDocument()
    })

    it('drills down and walks back through every level (uncontrolled)', async () => {
        render(<FilterPicker rootNodes={[propertyNode]} trigger={<button type="button">Add filter</button>} />)

        fireEvent.click(screen.getByText('Add filter'))
        fireEvent.click(await screen.findByRole('button', { name: 'Status' }))
        fireEvent.click(await screen.findByRole('button', { name: 'Equals' }))
        expect(await screen.findByRole('button', { name: 'Active' })).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Go back to previous filter level' }))
        expect(await screen.findByRole('button', { name: 'Equals' })).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Go back to previous filter level' }))
        expect(await screen.findByRole('button', { name: 'Status' })).toBeInTheDocument()
    })
})
