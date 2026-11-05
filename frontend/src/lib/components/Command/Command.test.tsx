import { act, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { Command } from './Command'
import { commandLogic } from './commandLogic'

// The first open mounts the search logic and every logic it connects to, which on CI takes longer than the
// 1 s findBy default and can take longer than the 5 s Jest default.
jest.setTimeout(20000)

const findSearchInput = (): Promise<HTMLInputElement> =>
    screen.findByPlaceholderText('Search or ask PostHog AI… try is:dashboard', {}, { timeout: 10000 })

describe('Command', () => {
    // Command loads the palette with a dynamic import. Loading the module here keeps its cold load out of
    // the test timeout, and the lazy component still suspends once on the first open.
    beforeAll(() => import('lib/components/CommandKSearch/CommandKSearch'))

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.NEW_COMMAND_K_SEARCH], {
            [FEATURE_FLAGS.NEW_COMMAND_K_SEARCH]: true,
        })
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
