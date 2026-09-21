import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef } from 'react'

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
                            items: [{ label: 'Summary', onClick: onSelect }],
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
        await userEvent.click(await screen.findByText('Summary'))

        expect(onSelect).toHaveBeenCalledTimes(1)
        expect(screen.getByText('Change view')).toBeInTheDocument()
        expect(screen.getByText('Summary')).toBeInTheDocument()

        await userEvent.click(screen.getByText('Outside'))

        await waitFor(() => {
            expect(screen.queryByText('Change view')).not.toBeInTheDocument()
            expect(screen.queryByText('Summary')).not.toBeInTheDocument()
        })
    })
})
