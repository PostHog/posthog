import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { ToastProvider, toast } from '@posthog/quill'

import { lemonToast } from './LemonToast'
import { setQuillToasts } from './quillToast'

describe('lemonToast on quill', () => {
    beforeEach(() => {
        render(<ToastProvider>{null}</ToastProvider>)
        setQuillToasts(toast)
    })

    afterEach(() => {
        act(() => lemonToast.dismiss())
        setQuillToasts(null)
        cleanup()
    })

    it('updates the visible toast when a toast reuses its id', async () => {
        act(() => {
            lemonToast.loading('Exporting', { toastId: 'export' })
        })
        expect(await screen.findByText('Exporting')).toBeInTheDocument()

        act(() => {
            lemonToast.updateToSuccess('export', 'Export ready')
        })

        expect(await screen.findByText('Export ready')).toBeInTheDocument()
        expect(screen.queryByText('Exporting')).not.toBeInTheDocument()
        expect(document.querySelectorAll('[data-attr="success-toast"]')).toHaveLength(1)
    })

    it('runs undo and closes the toast', async () => {
        const undo = jest.fn()
        act(() => {
            lemonToast.info('Dashboard deleted', { toastId: 'delete', button: { label: 'Undo', action: undo } })
        })

        fireEvent.click(await screen.findByText('Undo'))

        expect(undo).toHaveBeenCalledTimes(1)
        expect(lemonToast.isActive('delete')).toBe(false)
    })

    it('offers get help on an error unless told not to', async () => {
        act(() => {
            lemonToast.error('Could not save')
            lemonToast.error('Could not load', { hideButton: true })
        })

        expect(await screen.findByText('Could not save')).toBeInTheDocument()
        expect(await screen.findByText('Could not load')).toBeInTheDocument()
        expect(screen.getAllByText('Get help')).toHaveLength(1)
    })
})
