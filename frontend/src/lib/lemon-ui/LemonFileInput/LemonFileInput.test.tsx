import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonFileInput } from './LemonFileInput'

describe('LemonFileInput', () => {
    afterEach(() => {
        cleanup()
    })

    it('keeps the drop highlight while a drag moves over child elements and accepts the drop', () => {
        const onChange = jest.fn()
        const file = new File(['refunds'], 'refund-policy.md', { type: 'text/markdown' })
        const dataTransfer = { items: [{ kind: 'file' }], files: [file] }
        render(
            <LemonFileInput accept=".md" multiple={false} onChange={onChange} callToAction={<span>Drop here</span>} />
        )

        const child = screen.getByText('Drop here')
        const dropTarget = child.closest('.FileDropTarget') as HTMLElement

        fireEvent.dragEnter(dropTarget, { dataTransfer })
        fireEvent.dragEnter(child, { dataTransfer })
        fireEvent.dragLeave(dropTarget, { dataTransfer })
        expect(dropTarget).toHaveClass('FileDropTarget--active')

        fireEvent.drop(child, { dataTransfer })
        expect(dropTarget).not.toHaveClass('FileDropTarget--active')
        expect(onChange).toHaveBeenCalledWith([file])
    })
})
