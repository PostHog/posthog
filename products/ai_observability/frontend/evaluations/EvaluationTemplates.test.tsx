import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'

describe('EvaluationTemplates', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI], {
            [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI]: true,
        })
    })

    afterEach(cleanup)

    it('shows a PostHog MCP prompt for creating online evaluations', () => {
        render(<EvaluationTemplatesEmptyState />)

        expect(screen.getByText('Or do it from your agent')).toBeInTheDocument()
        expect(screen.getByText(/Use the connected PostHog MCP server/)).toHaveTextContent(
            'ask which evaluations I want you to create before creating anything'
        )
        expect(screen.queryByText('Start with AI')).not.toBeInTheDocument()
    })
})
