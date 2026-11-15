import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, type AppContext } from '~/types'

import { EvaluationsTabs } from './EvaluationsTabs'

describe('EvaluationsTabs', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...priorAppContext,
            effective_resource_access_control: {
                [AccessControlResourceType.Evaluation]: AccessControlLevel.None,
                [AccessControlResourceType.LlmAnalytics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it('does not link a tab the user cannot access', () => {
        render(<EvaluationsTabs activeTab="scorers" />)

        expect(screen.getByText('Online evals').closest('a')).toBeNull()
        expect(screen.getByText('Scorers').closest('a')).not.toBeNull()
    })
})
