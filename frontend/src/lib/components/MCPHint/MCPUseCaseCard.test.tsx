import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import * as clipboard from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'

import { mcpHintLogic } from './mcpHintLogic'
import { MCPUseCaseCard } from './MCPUseCaseCard'
import { getSurfacePrompts } from './prompts'

describe('MCPUseCaseCard', () => {
    beforeEach(() => {
        initKeaTests()
        jest.restoreAllMocks()
        mcpHintLogic.mount()
    })

    afterEach(cleanup)

    it('copies a surface configured to display a prompt', () => {
        const copySpy = jest.spyOn(clipboard, 'copyToClipboard').mockResolvedValue(true)
        const [prompt] = getSurfacePrompts('ai_observability_evaluations.create').examples

        render(<MCPUseCaseCard surfaceKey="ai_observability_evaluations.create" forceDisplay />)
        fireEvent.click(screen.getByLabelText('Copy to clipboard'))

        expect(copySpy).toHaveBeenCalledWith(prompt, 'prompt')
    })

    it('keeps a single dynamic SQL example in the list display', () => {
        mcpHintLogic.actions.loadTopEventsSuccess(['signup_completed'])

        render(<MCPUseCaseCard surfaceKey="sql.execute" forceDisplay />)

        expect(screen.getByText('"How many users triggered signup_completed yesterday?"')).toBeInTheDocument()
        expect(screen.queryByLabelText('Copy to clipboard')).not.toBeInTheDocument()
    })
})
