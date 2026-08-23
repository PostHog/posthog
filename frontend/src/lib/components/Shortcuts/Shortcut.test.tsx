import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { initKeaTests } from '~/test/init'

import { Shortcut } from './Shortcut'
import { shortcutLogic } from './shortcutLogic'

describe('Shortcut', () => {
    beforeEach(() => {
        initKeaTests()
        shortcutLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    // Regression: when Shortcut wraps a LemonDropdown-triggered button, its ref, tooltip, and data
    // attributes must land on the real trigger button. Nesting them the other way round sent them to
    // the floating overlay, so the keybind targeted an element that only exists while the menu is open.
    it('decorates the wrapped button, not the dropdown overlay', () => {
        render(
            <LemonDropdown overlay={<div>Menu content</div>} placement="bottom-end">
                <Shortcut name="Test" keybind={[['command', 'n']]} intent="Do the thing" interaction="click">
                    <LemonButton tooltip="New thing">Open</LemonButton>
                </Shortcut>
            </LemonDropdown>
        )

        const trigger = screen.getByRole('button', { name: 'Open' })
        expect(trigger).toHaveAttribute('data-shortcut-keybind', 'command+n')
    })

    it('forwards the dropdown click handler so the trigger opens the menu', async () => {
        render(
            <LemonDropdown overlay={<div>Menu content</div>} placement="bottom-end">
                <Shortcut name="Test" keybind={[['command', 'n']]} intent="Do the thing" interaction="click">
                    <LemonButton>Open</LemonButton>
                </Shortcut>
            </LemonDropdown>
        )

        expect(screen.queryByText('Menu content')).not.toBeInTheDocument()

        await userEvent.click(screen.getByRole('button', { name: 'Open' }))

        expect(screen.getByText('Menu content')).toBeInTheDocument()
    })
})
