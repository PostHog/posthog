import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'

import { initKeaTests } from '~/test/init'
import { PreflightStatus } from '~/types'

import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'

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

    it('replaces Start with AI with the evaluation prompt card', () => {
        render(<EvaluationTemplatesEmptyState />)

        expect(screen.getByText(/Use the connected PostHog MCP server/)).toBeInTheDocument()
        expect(screen.queryByText('Start with AI')).not.toBeInTheDocument()
    })
})
