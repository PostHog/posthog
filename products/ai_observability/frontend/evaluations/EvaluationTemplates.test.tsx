import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { EvaluationTemplatesEmptyState } from './EvaluationTemplates'

describe('EvaluationTemplates', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        sidePanelStateLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI], {
            [FEATURE_FLAGS.LLM_ANALYTICS_EVALUATIONS_START_WITH_AI]: true,
        })
    })

    afterEach(cleanup)

    it('opens PostHog AI in the context panel with an auto-run evaluation prompt', async () => {
        render(<EvaluationTemplatesEmptyState />)

        await userEvent.click(screen.getByText('Start with AI'))

        expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
        expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
        expect(sidePanelStateLogic.values.selectedTabOptions).toMatch(/^!Explore my recent AI traces/)
        expect(sidePanelStateLogic.values.selectedTabOptions).toContain('ask me which ones to set up')
    })
})
