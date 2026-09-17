import { api } from 'lib/api.mock'

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

function renderModal(userAccessLevel: AccessControlLevel): ReturnType<typeof experimentLogic.build> {
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

    return logic
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

    it('blocks the save while an experiment update is still in flight', async () => {
        useMocks(mocksFor(AccessControlLevel.Editor))
        const logic = renderModal(AccessControlLevel.Editor)
        jest.spyOn(api, 'update').mockImplementation(() => new Promise(() => {}))

        await waitFor(() =>
            expect(screen.getByText('Save').closest('button')).not.toHaveAttribute('aria-disabled', 'true')
        )

        // A save submitted now would compare against a baseline the pending update has not
        // refreshed yet, so a revert of the pending change would write nothing.
        logic.actions.updateExperiment({ name: 'pending' })

        await waitFor(() => expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled', 'true'))
    })
})
