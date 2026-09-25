import '@testing-library/jest-dom'

import { Menu } from '@base-ui/react/menu'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { keepSubmenuOpenOnRepeatPress } from './keepSubmenuOpenOnRepeatPress'

function Harness(): JSX.Element {
    return (
        <Menu.Root open>
            <Menu.Trigger>Account</Menu.Trigger>
            <Menu.Portal>
                <Menu.Positioner>
                    <Menu.Popup>
                        <Menu.SubmenuRoot onOpenChange={keepSubmenuOpenOnRepeatPress}>
                            <Menu.SubmenuTrigger openOnHover={false}>Project</Menu.SubmenuTrigger>
                            <Menu.Portal>
                                <Menu.Positioner>
                                    <Menu.Popup data-attr="submenu">
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

function pressTrigger(): void {
    fireEvent.mouseDown(screen.getByText('Project'), { button: 0 })
    act(() => jest.runOnlyPendingTimers())
}

// Base UI marks a closing popup with `data-closed` at once and unmounts it after its exit transition.
const submenu = (): HTMLElement | null => screen.queryByTestId('submenu')

describe('keepSubmenuOpenOnRepeatPress', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        render(<Harness />)
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('opens the submenu on a press of its trigger', () => {
        expect(submenu()).not.toBeInTheDocument()
        pressTrigger()
        expect(submenu()).not.toHaveAttribute('data-closed')
    })

    it('leaves the submenu open on a repeat press of its trigger', () => {
        pressTrigger()
        pressTrigger()
        expect(submenu()).not.toHaveAttribute('data-closed')
    })

    it('still closes the submenu on Escape', async () => {
        pressTrigger()
        fireEvent.keyDown(submenu()!, { key: 'Escape' })
        await waitFor(() => expect(submenu()).not.toBeInTheDocument())
    })

    it('still closes the submenu when an item is picked', async () => {
        pressTrigger()
        fireEvent.click(screen.getByText('Project A'))
        await waitFor(() => expect(submenu()).not.toBeInTheDocument())
    })
})
