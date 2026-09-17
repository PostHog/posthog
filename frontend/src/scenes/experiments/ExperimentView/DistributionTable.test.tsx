import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { featureFlagLogic as enabledFlagsLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { DistributionModal } from './DistributionTable'

jest.mock('~/scenes/experiments/ExperimentForm/VariantDistributionEditor', () => ({
    VariantDistributionEditor: () => <div data-attr="variant-distribution-editor" />,
    useVariantDistributionValidation: () => ({ areVariantRolloutsValid: true }),
}))

jest.mock('./HoldoutSelector', () => ({
    HoldoutSelector: () => <div data-attr="holdout-selector" />,
}))

const EXPERIMENT_ID = 123

function mocksFor(userAccessLevel: AccessControlLevel): Record<string, any> {
    return {
        get: {
            [`/api/projects/:team/experiments/${EXPERIMENT_ID}`]: () => [
                200,
                { id: EXPERIMENT_ID, user_access_level: userAccessLevel },
            ],
            '/api/projects/:team/experiment_holdouts': () => [200, { results: [], count: 0 }],
            '/api/projects/:team/experiment_saved_metrics': () => [200, { results: [], count: 0 }],
        },
    }
}

function renderModal(userAccessLevel: AccessControlLevel): void {
    initKeaTests()
    enabledFlagsLogic.mount()
    const logic = experimentLogic({ experimentId: EXPERIMENT_ID })
    logic.mount()
    logic.actions.setExperiment({ user_access_level: userAccessLevel })
    modalsLogic.mount()
    modalsLogic.actions.openDistributionModal()

    render(
        <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
            <DistributionModal />
        </BindLogic>
    )
}

describe('DistributionModal', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        [AccessControlLevel.Viewer, true],
        [AccessControlLevel.Editor, false],
    ])('experiment access %s blocks the save: %s', async (userAccessLevel, blocked) => {
        useMocks(mocksFor(userAccessLevel))
        renderModal(userAccessLevel)

        await waitFor(() => {
            const save = screen.getByText('Save').closest('button')
            if (blocked) {
                expect(save).toHaveAttribute('aria-disabled', 'true')
            } else {
                expect(save).not.toHaveAttribute('aria-disabled', 'true')
            }
        })
    })
})
