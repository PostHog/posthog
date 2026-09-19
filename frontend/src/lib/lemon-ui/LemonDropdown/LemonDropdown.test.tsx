import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonDropdown } from './LemonDropdown'

describe('LemonDropdown', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so the portal stays isolated.
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    // The press that opened the dropdown must not also count as an outside press, or the dismiss
    // and the trigger's own toggle cancel out and the dropdown can never be closed from its trigger.
    it.each([{ closeOnClickInside: true }, { closeOnClickInside: false }])(
        'closes on a second trigger click with closeOnClickInside $closeOnClickInside',
        async ({ closeOnClickInside }) => {
            const visibilities: boolean[] = []

            render(
                <LemonDropdown
                    closeOnClickInside={closeOnClickInside}
                    onVisibilityChange={(visible) => visibilities.push(visible)}
                    overlay={<div>Menu</div>}
                >
                    <button>Open</button>
                </LemonDropdown>
            )

            await userEvent.click(screen.getByText('Open'))
            await userEvent.click(screen.getByText('Open'))

            expect(visibilities).toEqual([true, false])
        }
    )

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
