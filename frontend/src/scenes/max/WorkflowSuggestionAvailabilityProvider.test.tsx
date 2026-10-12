import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'
import { useContext } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { WorkflowSuggestionAvailabilityContext } from 'products/posthog_ai/frontend/api/runner'

import { maxMocks } from './testUtils'
import { WorkflowSuggestionAvailabilityProvider } from './WorkflowSuggestionAvailabilityProvider'

function AvailabilityProbe(): JSX.Element {
    return <span>{String(useContext(WorkflowSuggestionAvailabilityContext))}</span>
}

describe('WorkflowSuggestionAvailabilityProvider', () => {
    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
    })

    afterEach(cleanup)

    it.each([
        { flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE], available: 'true' },
        { flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN], available: 'false' },
    ])('follows the scene integration gate without recording a workflow experiment exposure', (testCase) => {
        const capture = jest.spyOn(posthog, 'capture')
        featureFlagLogic.actions.setFeatureFlags([...testCase.flags, FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW], {
            ...Object.fromEntries(testCase.flags.map((flag) => [flag, true])),
            [FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW]: 'test',
        })

        render(
            <WorkflowSuggestionAvailabilityProvider>
                <AvailabilityProbe />
            </WorkflowSuggestionAvailabilityProvider>
        )

        expect(screen.getByText(testCase.available)).toBeInTheDocument()
        expect(capture).not.toHaveBeenCalledWith(
            '$feature_flag_called',
            expect.objectContaining({ $feature_flag: FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW })
        )
    })
})
