import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonDropdown } from './LemonDropdown'

describe('LemonDropdown', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so the portal stays isolated.
    afterEach(() => {
        cleanup()
    })

    // `e.relatedTarget` on a mouseleave is null when the cursor leaves the document and can be a
    // non-Node (the Window) when it exits the viewport — both used to reach `Node.contains()` and
    // throw "parameter 1 is not of type 'Node'". The overlay must be open so the refs are populated.
    it.each([
        { desc: 'null relatedTarget', relatedTarget: null },
        { desc: 'non-Node relatedTarget (window)', relatedTarget: window },
    ])('does not throw on a hover mouseleave with $desc', ({ relatedTarget }) => {
        const onVisibilityChange = jest.fn()

        render(
            <LemonDropdown
                trigger="hover"
                startVisible
                onVisibilityChange={onVisibilityChange}
                overlay={<div>Menu</div>}
            >
                <button>Open</button>
            </LemonDropdown>
        )

        const trigger = screen.getByRole('button', { name: 'Open' })
        const overlay = document.querySelector('.Popover')
        expect(overlay).toBeInTheDocument()

        // Child trigger's onMouseLeave (guards against floatingRef.current.contains).
        expect(() => fireEvent.mouseLeave(trigger, { relatedTarget })).not.toThrow()
        // Overlay's onMouseLeaveInside (guards against referenceRef.current.contains).
        expect(() => fireEvent.mouseLeave(overlay!, { relatedTarget })).not.toThrow()

        // The "cursor has left" branch should still run, closing the dropdown.
        expect(onVisibilityChange).toHaveBeenCalledWith(false)
    })
})
