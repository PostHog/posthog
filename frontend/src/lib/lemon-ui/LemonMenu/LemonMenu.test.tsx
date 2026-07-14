import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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
})
