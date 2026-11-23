import { act, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { Command } from './Command'
import { commandLogic } from './commandLogic'

// On CI, the first open mounts enough connected logics to outlast the findBy and Jest default timeouts.
jest.setTimeout(20000)

const findSearchInput = (): Promise<HTMLInputElement> =>
    screen.findByLabelText<HTMLInputElement>('Search', {}, { timeout: 10000 })

describe('Command', () => {
    // Keeps the cold load of the lazy chunk out of the test. The lazy component still suspends on the first open.
    beforeAll(() => import('lib/components/CommandKSearch/CommandKSearch'))

    beforeEach(() => {
        initKeaTests()
        commandLogic.mount()
    })

    it('opens Command K search with an empty query after it closes with a query', async () => {
        render(<Command />)
        act(() => commandLogic.actions.openCommand('keyboard-shortcut'))
        fireEvent.change(await findSearchInput(), { target: { value: 'work', selectionStart: 4 } })
        expect((await findSearchInput()).value).toBe('work')

        act(() => commandLogic.actions.closeCommand())
        act(() => commandLogic.actions.openCommand('keyboard-shortcut'))

        expect((await findSearchInput()).value).toBe('')
    })
})
