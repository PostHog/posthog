import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'

import { LemonButton } from '../LemonButton'
import { LemonMenu, LemonMenuItems } from './LemonMenu'

describe('LemonMenu', () => {
    // jest.setupAfterEnv does not enable RTL auto-cleanup; unmount between tests so `screen` stays isolated.
    afterEach(() => {
        cleanup()
    })

    it('forwards its ref to the trigger DOM node', () => {
        let resolvedNode: HTMLElement | null = null

        render(
            <LemonMenu
                items={[{ label: 'First', to: '/first' }]}
                ref={(node) => {
                    resolvedNode = node
                }}
            >
                <LemonButton>Open</LemonButton>
            </LemonMenu>
        )

        // The ref must land on the real trigger button, not on the (DOM-less) LemonMenu component.
        expect(resolvedNode).toBeInstanceOf(HTMLButtonElement)
        expect(resolvedNode).toBe(screen.getByRole('button'))
    })

    it('clicking the ref-driven trigger opens the menu', async () => {
        function Wrapper(): JSX.Element {
            const ref = useRef<HTMLElement>(null)
            return (
                <>
                    <button onClick={() => ref.current?.click()}>Trigger via ref</button>
                    <LemonMenu items={[{ label: 'First', to: '/first' }]} ref={ref}>
                        <LemonButton>Open</LemonButton>
                    </LemonMenu>
                </>
            )
        }

        render(<Wrapper />)

        expect(screen.queryByText('First')).not.toBeInTheDocument()

        // Triggering a click through the forwarded ref (as <Shortcut /> does) must open the menu.
        await userEvent.click(screen.getByText('Trigger via ref'))

        expect(screen.getByText('First')).toBeInTheDocument()
    })

    it('keyboard navigation reaches items added after mount without crashing', async () => {
        let grow: () => void = () => {}
        function Wrapper(): JSX.Element {
            const [items, setItems] = useState<LemonMenuItems>([{ label: 'First', to: '/first' }])
            grow = () =>
                setItems([
                    { label: 'First', to: '/first' },
                    { label: 'Second', to: '/second' },
                    { label: 'Third', to: '/third' },
                ])
            return (
                <LemonMenu items={items} startVisible>
                    <LemonButton>Open</LemonButton>
                </LemonMenu>
            )
        }

        render(<Wrapper />)

        // The menu is sized for one item at mount; grow it past that initial count.
        act(() => grow())

        // Keyboard navigation is driven from the focused trigger.
        act(() => screen.getByText('Open').closest('button')!.focus())

        // Arrow-key navigation onto the newly added indices must move focus, not throw
        // "Cannot read properties of undefined (reading 'current')" from the stale ref array.
        const third = screen.getByText('Third').closest('a')!
        await userEvent.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}')

        expect(third).toHaveFocus()
    })
})
