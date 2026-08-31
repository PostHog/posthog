import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { commandLogic } from 'lib/components/Command/commandLogic'

import { initKeaTests } from '~/test/init'

import { NavSearchBar, NavSearchButton } from './NavSearchButton'

function ConnectedNavSearchButton(): JSX.Element {
    const { openCommand } = useActions(commandLogic)
    const { isCommandOpen } = useValues(commandLogic)
    return <NavSearchButton openCommand={openCommand} isCommandOpen={isCommandOpen} />
}

function ConnectedNavSearchBar(): JSX.Element {
    const { openCommand } = useActions(commandLogic)
    const { isCommandOpen } = useValues(commandLogic)
    return <NavSearchBar openCommand={openCommand} isCommandOpen={isCommandOpen} />
}

describe('NavSearchButton', () => {
    beforeEach(() => {
        initKeaTests()
        commandLogic.mount()
    })

    afterEach(cleanup)

    test.each([
        ['icon trigger', ConnectedNavSearchButton, 'nav-search'],
        ['bar trigger', ConnectedNavSearchBar, 'nav-search-bar'],
    ])('%s keeps the palette open on a repeat click and reflects the pressed state', (_name, Trigger, dataAttr) => {
        const { container } = render(<Trigger />)
        const button = container.querySelector(`[data-attr="${dataAttr}"]`) as HTMLButtonElement

        expect(button).toHaveAttribute('aria-pressed', 'false')

        fireEvent.click(button)
        expect(commandLogic.values.isCommandOpen).toBe(true)
        expect(button).toHaveAttribute('aria-pressed', 'true')

        // A second, impatient click must not toggle the palette shut.
        fireEvent.click(button)
        expect(commandLogic.values.isCommandOpen).toBe(true)
    })
})
