import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ButtonHTMLAttributes, forwardRef, useRef, useState } from 'react'

import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'

import { LemonButton } from '../LemonButton'
import { LemonMenu } from './LemonMenu'

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

    it('can keep a nested menu open until the user clicks outside', async () => {
        const onSelect = jest.fn()

        render(
            <div>
                <LemonMenu
                    items={[
                        {
                            label: 'Change view',
                            closeOnClickInside: false,
                            closeParentPopoverOnClickInside: false,
                            items: [{ label: 'Summary', onClick: onSelect }, { label: 'Details' }],
                        },
                    ]}
                >
                    <LemonButton>More actions</LemonButton>
                </LemonMenu>
                <button type="button">Outside</button>
            </div>
        )

        await userEvent.click(screen.getByText('More actions'))
        await userEvent.click(await screen.findByText('Change view'))
        const summary = (await screen.findByText('Summary')).closest('button')!
        await userEvent.keyboard('{ArrowDown}')
        expect(summary).toHaveFocus()
        await userEvent.keyboard('{ArrowDown}')
        expect(screen.getByText('Details').closest('button')).toHaveFocus()
        await userEvent.keyboard('{ArrowUp}')
        expect(summary).toHaveFocus()
        await userEvent.click(summary)

        expect(onSelect).toHaveBeenCalledTimes(1)
        expect(screen.getByText('Change view')).toBeInTheDocument()
        expect(screen.getByText('Summary')).toBeInTheDocument()

        await userEvent.click(screen.getByText('Outside'))

        await waitFor(() => {
            expect(screen.queryByText('Change view')).not.toBeInTheDocument()
            expect(screen.queryByText('Summary')).not.toBeInTheDocument()
        })
    })

    it('moves focus past a closed submenu trigger to the next item', async () => {
        render(
            <LemonMenu items={[{ label: 'Change view', items: [{ label: 'Summary' }] }, { label: 'Export' }]}>
                <LemonButton>More actions</LemonButton>
            </LemonMenu>
        )

        await userEvent.click(screen.getByText('More actions'))
        const changeView = (await screen.findByText('Change view')).closest('button')!
        await userEvent.keyboard('{ArrowDown}')
        expect(changeView).toHaveFocus()
        await userEvent.keyboard('{ArrowDown}')
        expect(screen.getByText('Export').closest('button')).toHaveFocus()
        expect(screen.queryByText('Summary')).not.toBeInTheDocument()
    })

    it('starts arrow navigation from a clicked item', async () => {
        render(
            <LemonMenu
                items={[{ items: [{ label: 'First' }, { label: 'Second' }, false] }, { items: [{ label: 'Third' }] }]}
                closeOnClickInside={false}
            >
                <LemonButton>Open</LemonButton>
            </LemonMenu>
        )

        await userEvent.click(screen.getByText('Open'))
        const second = (await screen.findByText('Second')).closest('button')!
        await userEvent.click(second)
        await userEvent.keyboard('{ArrowDown}')
        expect(screen.getByText('Third').closest('button')).toHaveFocus()
        await userEvent.keyboard('{ArrowUp}')
        expect(second).toHaveFocus()
    })

    it('accepts arrow keys from a button inside a wrapper trigger', async () => {
        const WrappedButton = forwardRef<HTMLDivElement, ButtonHTMLAttributes<HTMLButtonElement>>(
            function WrappedButton(props, ref) {
                return (
                    <div ref={ref}>
                        <button type="button" disabled>
                            Unavailable
                        </button>
                        <button type="button" {...props} />
                    </div>
                )
            }
        )
        render(
            <LemonMenu items={[{ label: 'First' }, { label: 'Second' }]}>
                <WrappedButton>Open</WrappedButton>
            </LemonMenu>
        )

        const trigger = screen.getByText('Open')
        await userEvent.click(trigger)
        const first = (await screen.findByText('First')).closest('button')
        await userEvent.keyboard('{ArrowDown}')
        expect(first).toHaveFocus()
        await userEvent.keyboard('{ArrowUp}')
        expect(trigger).toHaveFocus()
    })

    it('navigates to items added after the menu opens', async () => {
        const { rerender } = render(
            <LemonMenu items={[{ label: 'First' }]}>
                <LemonButton>Open</LemonButton>
            </LemonMenu>
        )

        await userEvent.click(screen.getByText('Open'))
        await screen.findByText('First')
        rerender(
            <LemonMenu items={[{ label: 'First' }, { label: 'Second' }]}>
                <LemonButton>Open</LemonButton>
            </LemonMenu>
        )
        await userEvent.keyboard('{ArrowDown}{ArrowDown}')
        expect(screen.getByText('Second').closest('button')).toHaveFocus()
    })

    it('navigates portal items inside a shadow root', async () => {
        const host = document.createElement('div')
        document.body.appendChild(host)
        const shadowRoot = host.attachShadow({ mode: 'open' })
        const container = shadowRoot.appendChild(document.createElement('div'))

        function ShadowMenu(): JSX.Element {
            const [floatingContainer, setFloatingContainer] = useState<HTMLDivElement | null>(null)
            return (
                <FloatingContainerContext.Provider value={floatingContainer}>
                    <LemonMenu items={[{ label: 'First' }, { label: 'Second' }]}>
                        <LemonButton>Open</LemonButton>
                    </LemonMenu>
                    <div ref={setFloatingContainer} />
                </FloatingContainerContext.Provider>
            )
        }
        const { getByText, findByText } = render(<ShadowMenu />, { container })

        await userEvent.click(getByText('Open'))
        const first = (await findByText('First')).closest('button')
        await userEvent.keyboard('{ArrowDown}')
        expect(shadowRoot.activeElement).toBe(first)
        await userEvent.keyboard('{ArrowDown}')
        expect(shadowRoot.activeElement).toBe(getByText('Second').closest('button'))
        host.remove()
    })

    it.each([false, true])('navigates and reopens with startVisible=%s', async (startVisible) => {
        render(
            <div>
                <LemonMenu
                    startVisible={startVisible}
                    items={[
                        { title: <div>Available sources</div>, items: [] },
                        { label: 'First' },
                        { label: 'Second' },
                    ]}
                >
                    <LemonButton>Open</LemonButton>
                </LemonMenu>
                <button type="button">Outside</button>
            </div>
        )

        const trigger = screen.getByText('Open').closest('button')!
        for (let opening = 0; opening < 2; opening++) {
            if (!startVisible || opening > 0) {
                await userEvent.click(trigger)
            }
            const first = (await screen.findByText('First')).closest('button')!
            if (startVisible && opening === 0) {
                first.focus()
                await userEvent.keyboard('{ArrowUp}')
                expect(trigger).toHaveFocus()
            }
            const second = screen.getByText('Second').closest('button')!
            await userEvent.keyboard('{ArrowDown}')
            expect(first).toHaveFocus()
            await userEvent.keyboard('{ArrowDown}')
            expect(second).toHaveFocus()
            await userEvent.keyboard('{ArrowUp}')
            expect(first).toHaveFocus()
            await userEvent.keyboard('{ArrowUp}')
            expect(trigger).toHaveFocus()
            await userEvent.keyboard('{ArrowDown}{ArrowDown}')
            expect(second).toHaveFocus()
            await userEvent.click(screen.getByText('Outside'))
            await waitFor(() => expect(screen.queryByText('First')).not.toBeInTheDocument())
        }
    })
})
