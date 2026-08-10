import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { MCP_INSTALL_COMMAND } from 'lib/components/MCPHint/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'
import { PreflightStatus } from '~/types'

import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

describe('EvaluationTemplates', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI], {
            [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI]: true,
        })
        preflightLogic.actions.loadPreflightSuccess({ cloud: true } as PreflightStatus)
    })

    afterEach(cleanup)

    it('shows the MCP setup command before a copyable evaluation prompt', () => {
        const { container } = render(<EvaluationTemplatesEmptyState />)

        expect(screen.getByText('Create evaluations with your AI agent')).toBeInTheDocument()
        expect(screen.getByText(MCP_INSTALL_COMMAND)).toBeInTheDocument()

        const installCommand = screen.getByLabelText('Copy MCP install command')
        const prompt = screen.getByText(/Use the connected PostHog MCP server/)
        expect(installCommand.compareDocumentPosition(prompt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(prompt).toHaveTextContent('ask which evaluations I want you to create before creating anything')

        fireEvent.click(container.querySelector('[data-attr="copy-code-button"]')!)

        expect(copyToClipboard).toHaveBeenCalledWith(
            "Use the connected PostHog MCP server and this project's AI observability data to inspect recent traces. Identify and rank real failure modes, recommend one online evaluation per distinct failure mode, then ask which evaluations I want you to create before creating anything.",
            'evaluation prompt'
        )
        expect(screen.queryByText('Start with AI')).not.toBeInTheDocument()
    })
})
