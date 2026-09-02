import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'

import { mcpHintLogic } from './mcpHintLogic'
import { MCPUseCaseCard } from './MCPUseCaseCard'
import { getSurfacePrompts } from './prompts'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

describe('MCPUseCaseCard', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mcpHintLogic.mount()
    })

    afterEach(cleanup)

    it('copies a surface configured to display a prompt', () => {
        const [prompt] = getSurfacePrompts('ai_observability_evaluations.create').examples

        render(<MCPUseCaseCard surfaceKey="ai_observability_evaluations.create" forceDisplay />)
        fireEvent.click(screen.getByLabelText('Copy to clipboard'))

        expect(copyToClipboard).toHaveBeenCalledWith(prompt, 'prompt')
    })

    it('keeps a single dynamic SQL example in the list display', () => {
        mcpHintLogic.actions.loadTopEventsSuccess(['signup_completed'])

        render(<MCPUseCaseCard surfaceKey="sql.execute" forceDisplay />)

        expect(screen.getByText('"How many users triggered signup_completed yesterday?"')).toBeInTheDocument()
        expect(screen.queryByLabelText('Copy to clipboard')).not.toBeInTheDocument()
    })
})
