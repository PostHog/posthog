import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonDropdown } from './LemonDropdown'

describe('LemonDropdown', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so the portal stays isolated.
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    // Regression: pressing the trigger registers as a floating-ui outside press unless the trigger is
    // the reference, so an open click-triggered dropdown used to dismiss itself immediately (every
    // `More` ellipsis menu looked dead). The trigger click must open the menu and leave it open, then
    // a second click must close it.
    it('opens on a trigger click, stays open, and closes on a second click', async () => {
        render(
            <LemonDropdown overlay={<div>Menu</div>}>
                <button>Open</button>
            </LemonDropdown>
        )
        const trigger = screen.getByText('Open')

        await userEvent.click(trigger)
        expect(screen.getByText('Menu')).toBeInTheDocument()

        await userEvent.click(trigger)
        await waitFor(() => expect(screen.queryByText('Menu')).not.toBeInTheDocument())
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
