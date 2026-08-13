import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonDropdown } from './LemonDropdown'

describe('LemonDropdown', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so the portal stays isolated.
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    // Clicking the trigger of an open dropdown must close it. The press fires floating-ui's
    // outside-press dismiss on `pointerdown` and the trigger's own toggle on `click`. Without the
    // reference exemption in Popover, the dismiss closes the menu and the toggle then reopens it in
    // the same gesture, so the menu stays open. This mirrors the stuck signup role dropdown.
    it('closes when the trigger is clicked while open, without reopening', () => {
        jest.useFakeTimers()

        render(
            <LemonDropdown startVisible overlay={<div>Menu</div>}>
                <button>Open</button>
            </LemonDropdown>
        )

        expect(screen.getByText('Menu')).toBeInTheDocument()

        // Flush the pointerdown and the click separately, so a dismiss on pointerdown commits
        // before the trigger's toggle reads visibility — the ordering that used to reopen the menu.
        const trigger = screen.getByText('Open')
        fireEvent.pointerDown(trigger)
        fireEvent.click(trigger)

        act(() => jest.advanceTimersByTime(50)) // let the exit transition unmount the portal

        expect(screen.queryByText('Menu')).not.toBeInTheDocument()
    })

    it('delays opening a hover dropdown when configured', () => {
        jest.useFakeTimers()
        const onVisibilityChange = jest.fn()

        render(
            <LemonDropdown
                trigger="hover"
                hoverOpenDelayMs={500}
                onVisibilityChange={onVisibilityChange}
                overlay={<div>Menu</div>}
            >
                <button>Open</button>
            </LemonDropdown>
        )

        fireEvent.mouseEnter(screen.getByText('Open'))
        expect(onVisibilityChange).not.toHaveBeenCalled()

        act(() => jest.advanceTimersByTime(499))
        expect(onVisibilityChange).not.toHaveBeenCalled()

        act(() => jest.advanceTimersByTime(1))
        expect(onVisibilityChange).toHaveBeenCalledWith(true)
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

        const trigger = screen.getByText('Open')
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
