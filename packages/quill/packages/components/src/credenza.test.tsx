import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { Credenza, CredenzaBody, CredenzaContent, CredenzaHeader, CredenzaTitle, CredenzaTrigger } from './credenza'

const originalMatchMedia = window.matchMedia

/** A viewport that matches the dialog breakpoint while `wide` is true, and can resize later. */
function mockViewport(wide: boolean): { resize: (nextWide: boolean) => void } {
    let matches = wide
    const listeners = new Set<() => void>()
    window.matchMedia = ((query: string) => ({
        get matches() {
            return matches
        },
        media: query,
        addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
        removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    })) as unknown as typeof window.matchMedia
    return {
        resize: (nextWide) => {
            matches = nextWide
            act(() => listeners.forEach((listener) => listener()))
        },
    }
}

function RenameCredenza(): JSX.Element {
    return (
        <Credenza>
            <CredenzaTrigger>Rename</CredenzaTrigger>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Rename dashboard</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody>
                    <input aria-label="Name" />
                </CredenzaBody>
            </CredenzaContent>
        </Credenza>
    )
}

const popupSlot = (): string | null => screen.getByRole('dialog').getAttribute('data-slot')

describe('Credenza', () => {
    afterEach(() => {
        cleanup()
        window.matchMedia = originalMatchMedia
    })

    it.each([
        { viewport: 'wide', wide: true, slot: 'dialog-content' },
        { viewport: 'phone', wide: false, slot: 'drawer-content' },
    ])('opens as $slot on a $viewport viewport', async ({ wide, slot }) => {
        mockViewport(wide)
        render(<RenameCredenza />)

        await userEvent.click(screen.getByText('Rename'))

        expect(popupSlot()).toBe(slot)
        expect(screen.getByRole('dialog').getAttribute('aria-labelledby')).toBe(screen.getByText('Rename dashboard').id)
    })

    it('keeps the drawer and its input while open, then follows the viewport after it closes', async () => {
        const viewport = mockViewport(false)
        render(<RenameCredenza />)
        await userEvent.click(screen.getByText('Rename'))
        await userEvent.type(screen.getByLabelText('Name'), 'Weekly growth')

        viewport.resize(true)

        expect(popupSlot()).toBe('drawer-content')
        expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Weekly growth')

        await userEvent.keyboard('{Escape}')
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
        await waitFor(() => expect(document.activeElement).toBe(screen.getByText('Rename')))
        await userEvent.click(screen.getByText('Rename'))

        expect(popupSlot()).toBe('dialog-content')
    })
})
