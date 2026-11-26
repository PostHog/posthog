import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ImpersonationReasonModal } from './ImpersonationReasonModal'

describe('ImpersonationReasonModal', () => {
    afterEach(cleanup)

    it('keeps the modal open while confirming and allows cancellation after loading ends', () => {
        const onClose = (): void => rerender(<></>)
        const { rerender } = render(
            <ImpersonationReasonModal
                inline
                isOpen
                loading
                onClose={onClose}
                onConfirm={jest.fn()}
                title="Log in as user"
            />
        )

        expect(screen.getByText('Cancel').closest('button')).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(screen.getByText('Cancel'))
        expect(screen.getByText('Log in as user')).toBeInTheDocument()

        rerender(
            <ImpersonationReasonModal inline isOpen onClose={onClose} onConfirm={jest.fn()} title="Log in as user" />
        )
        fireEvent.click(screen.getByText('Cancel'))
        expect(screen.queryByText('Log in as user')).not.toBeInTheDocument()
    })

    it('pre-fills the reason input with the initial reason', () => {
        render(
            <ImpersonationReasonModal
                inline
                isOpen
                onConfirm={jest.fn()}
                title="Upgrade to read-write impersonation"
                initialReason="support ticket #123"
            />
        )

        expect(screen.getByDisplayValue('support ticket #123')).toBeInTheDocument()
    })

    it('starts empty when no initial reason is provided', () => {
        render(<ImpersonationReasonModal inline isOpen onConfirm={jest.fn()} title="Change impersonated user" />)

        expect(screen.getByPlaceholderText('e.g., Customer support request #12345')).toHaveValue('')
    })

    it('confirms with the pre-filled reason without re-typing', () => {
        const onConfirm = jest.fn()
        render(
            <ImpersonationReasonModal
                inline
                isOpen
                onConfirm={onConfirm}
                title="Upgrade to read-write impersonation"
                confirmText="Upgrade"
                initialReason="support ticket #123"
            />
        )

        fireEvent.click(screen.getByText('Upgrade'))

        expect(onConfirm).toHaveBeenCalledWith('support ticket #123')
    })
})
