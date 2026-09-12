import '@testing-library/jest-dom'

import { Menu } from '@base-ui/react/menu'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { SUBMENU_TRAVEL_STALL_MS, useClickSubmenu } from './useClickSubmenu'

// The submenu sits to the right of the parent menu; "Invite members" sits right below the trigger row.
const SUBMENU_RECT = { left: 200, right: 400, top: 0, bottom: 300, x: 200, y: 0, width: 200, height: 300 }

function AccountMenuLikeHarness(): JSX.Element {
    const submenu = useClickSubmenu()
    return (
        <Menu.Root open>
            <Menu.Trigger>Account</Menu.Trigger>
            <Menu.Portal>
                <Menu.Positioner>
                    <Menu.Popup>
                        <Menu.SubmenuRoot {...submenu.rootProps}>
                            <Menu.SubmenuTrigger {...submenu.triggerProps}>Project</Menu.SubmenuTrigger>
                            <Menu.Portal>
                                <Menu.Positioner>
                                    <Menu.Popup {...submenu.popupProps} data-attr="submenu">
                                        <Menu.Item>Project A</Menu.Item>
                                    </Menu.Popup>
                                </Menu.Positioner>
                            </Menu.Portal>
                        </Menu.SubmenuRoot>
                        <Menu.Item>Invite members</Menu.Item>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}

function clickTrigger(): void {
    fireEvent.mouseDown(screen.getByText('Project'), { button: 0 })
    act(() => jest.runOnlyPendingTimers())
}

function openSubmenu(): HTMLElement {
    clickTrigger()
    const popup = screen.getByTestId('submenu')
    jest.spyOn(popup, 'getBoundingClientRect').mockReturnValue(SUBMENU_RECT as DOMRect)
    return popup
}

function leaveTriggerTowards(x: number, y: number): void {
    fireEvent.mouseLeave(screen.getByText('Project'), { clientX: 100, clientY: 15 })
    fireEvent.mouseMove(screen.getByText('Invite members'), { clientX: x, clientY: y })
}

// Base UI marks a closing popup with `data-closed` at once and unmounts it after its exit transition.
const submenu = (): HTMLElement | null => screen.queryByTestId('submenu')

describe('useClickSubmenu', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        render(<AccountMenuLikeHarness />)
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('opens the submenu on click', () => {
        expect(submenu()).not.toBeInTheDocument()
        clickTrigger()
        expect(submenu()).not.toHaveAttribute('data-closed')
    })

    it('keeps the submenu open while the pointer crosses a sibling item on its way to the submenu', () => {
        openSubmenu()

        leaveTriggerTowards(150, 100)
        fireEvent.mouseMove(screen.getByText('Invite members'), { clientX: 190, clientY: 180 })

        expect(submenu()).not.toHaveAttribute('data-closed')
    })

    it('closes the submenu when the pointer heads for a sibling item instead of the submenu', async () => {
        openSubmenu()

        leaveTriggerTowards(110, 250)

        await waitFor(() => expect(submenu()).not.toBeInTheDocument())
    })

    it('closes the submenu when the pointer stalls on a sibling item on the way', async () => {
        openSubmenu()

        leaveTriggerTowards(150, 100)
        act(() => jest.advanceTimersByTime(SUBMENU_TRAVEL_STALL_MS + 1))
        fireEvent.mouseMove(screen.getByText('Invite members'), { clientX: 160, clientY: 110 })

        await waitFor(() => expect(submenu()).not.toBeInTheDocument())
    })

    it('leaves the submenu open on a repeat click of its trigger', () => {
        openSubmenu()

        clickTrigger()

        expect(submenu()).not.toHaveAttribute('data-closed')
    })

    it('still closes the submenu on Escape', async () => {
        const popup = openSubmenu()

        fireEvent.keyDown(popup, { key: 'Escape' })

        await waitFor(() => expect(submenu()).not.toBeInTheDocument())
    })
})
