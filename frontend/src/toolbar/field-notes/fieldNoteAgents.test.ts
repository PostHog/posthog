import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { sendPromptToAgent } from './fieldNoteAgents'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

describe('sendPromptToAgent', () => {
    const open = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        window.open = open
    })

    it('opens the deep link of the chosen agent', async () => {
        await sendPromptToAgent('claude-code', 'fix this')

        expect(open).toHaveBeenCalledWith('claude-cli://open?q=fix%20this', '_blank')
        expect(copyToClipboard).not.toHaveBeenCalled()
    })

    it('falls back to the clipboard for a destination it does not know', async () => {
        await sendPromptToAgent('an-agent-we-dropped', 'fix this')

        expect(open).not.toHaveBeenCalled()
        expect(copyToClipboard).toHaveBeenCalledWith('fix this', 'field notes prompt')
    })
})
