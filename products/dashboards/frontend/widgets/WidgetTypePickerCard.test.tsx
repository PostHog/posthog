import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import { WidgetTypePickerCard } from './WidgetTypePickerCard'

describe('WidgetTypePickerCard', () => {
    afterEach(() => {
        cleanup()
    })
    it('shows empty circle when unselected and check in filled circle when selected', () => {
        const { rerender } = render(
            <WidgetTypePickerCard
                label="Error tracking"
                description="Top issues"
                selected={false}
                preview={<div>Preview</div>}
                onSelect={jest.fn()}
            />
        )

        let checkbox = screen.getByRole('checkbox', { name: 'Error tracking' })
        expect(checkbox).toHaveAttribute('aria-checked', 'false')

        let indicator = checkbox.querySelector('[aria-hidden="true"]')
        expect(indicator).toHaveClass('border-2')
        expect(indicator?.querySelector('svg')).not.toBeInTheDocument()

        rerender(
            <WidgetTypePickerCard
                label="Error tracking"
                description="Top issues"
                selected={true}
                preview={<div>Preview</div>}
                onSelect={jest.fn()}
            />
        )

        checkbox = screen.getByRole('checkbox', { name: 'Error tracking' })
        expect(checkbox).toHaveAttribute('aria-checked', 'true')
        indicator = checkbox.querySelector('[aria-hidden="true"]')
        expect(indicator?.querySelector('svg')).toBeInTheDocument()
    })

    it('deselects when clicking an already-selected card', async () => {
        function TogglePicker(): JSX.Element {
            const [selected, setSelected] = useState(true)

            return (
                <>
                    <WidgetTypePickerCard
                        label="Logs widget"
                        description="Recent log lines"
                        selected={selected}
                        preview={<div>Preview</div>}
                        onSelect={() => setSelected((current) => !current)}
                    />
                    <span data-attr="selected-state">{selected ? 'selected' : 'deselected'}</span>
                </>
            )
        }

        render(<TogglePicker />)

        expect(screen.getByRole('checkbox', { name: 'Logs widget' })).toHaveAttribute('aria-checked', 'true')
        expect(screen.getByTestId('selected-state')).toHaveTextContent('selected')

        await userEvent.click(screen.getByRole('checkbox', { name: 'Logs widget' }))

        expect(screen.getByRole('checkbox', { name: 'Logs widget' })).toHaveAttribute('aria-checked', 'false')
        expect(screen.getByTestId('selected-state')).toHaveTextContent('deselected')
    })

    it('calls onSelect on click and keyboard activation', async () => {
        const onSelect = jest.fn()
        render(
            <WidgetTypePickerCard
                label="Logs widget"
                description="Recent log lines"
                selected={false}
                preview={<div>Preview</div>}
                onSelect={onSelect}
            />
        )

        const checkbox = screen.getByRole('checkbox', { name: 'Logs widget' })
        await userEvent.click(checkbox)
        expect(onSelect).toHaveBeenCalledTimes(1)

        checkbox.focus()
        await userEvent.keyboard('{Enter}')
        expect(onSelect).toHaveBeenCalledTimes(2)

        await userEvent.keyboard(' ')
        expect(onSelect).toHaveBeenCalledTimes(3)
    })

    it('selects card when clicking preview content', async () => {
        const onSelect = jest.fn()
        render(
            <WidgetTypePickerCard
                label="Error tracking"
                description="Top issues"
                selected={false}
                preview={<div data-attr="preview-row">Preview row</div>}
                onSelect={onSelect}
            />
        )

        await userEvent.click(screen.getByTestId('preview-row'))

        expect(onSelect).toHaveBeenCalledTimes(1)
    })

    it('marks preview content as non-interactive', () => {
        render(
            <WidgetTypePickerCard
                label="Error tracking"
                description="Top issues"
                selected={false}
                preview={<div data-attr="preview-content">Preview</div>}
                onSelect={jest.fn()}
            />
        )

        const previewWrapper = screen.getByTestId('preview-content').parentElement
        expect(previewWrapper).toHaveClass('pointer-events-none')
        expect(previewWrapper).toHaveClass('select-none')
        expect(previewWrapper).toHaveAttribute('aria-hidden', 'true')
    })
})
