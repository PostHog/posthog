import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { featureFlagLogic as enabledFlagsLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, FeatureFlagBasicType, FeatureFlagType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { ReleaseConditionsModal } from './ReleaseConditionsTable'

jest.mock('scenes/feature-flags/FeatureFlagReleaseConditions', () => ({
    FeatureFlagReleaseConditions: () => <div data-attr="release-conditions-editor" />,
}))

const EXPERIMENT_ID = 123
const FLAG_ID = 456

function flagWithAccess(userAccessLevel: AccessControlLevel): Partial<FeatureFlagType> {
    return {
        id: FLAG_ID,
        key: 'experiment-flag',
        name: '',
        filters: { groups: [{ properties: [], rollout_percentage: 100 }], payloads: {}, multivariate: null },
        active: true,
        deleted: false,
        archived: false,
        user_access_level: userAccessLevel,
        can_edit: userAccessLevel === AccessControlLevel.Editor,
    }
}

function mocksFor(userAccessLevel: AccessControlLevel): Record<string, any> {
    return {
        get: {
            [`/api/projects/:team/experiments/${EXPERIMENT_ID}`]: () => [200, { id: EXPERIMENT_ID }],
            [`/api/projects/:team/feature_flags/${FLAG_ID}`]: () => [200, flagWithAccess(userAccessLevel)],
            '/api/projects/:team/feature_flags': () => [200, { results: [], count: 0 }],
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
    logic.actions.setExperiment({
        feature_flag: { ...flagWithAccess(userAccessLevel), team_id: MOCK_TEAM_ID } as FeatureFlagBasicType,
    })
    modalsLogic.mount()
    modalsLogic.actions.openReleaseConditionsModal()

    render(
        <BindLogic logic={experimentLogic} props={{ experimentId: EXPERIMENT_ID }}>
            <ReleaseConditionsModal />
        </BindLogic>
    )
}

describe('ReleaseConditionsModal', () => {
    afterEach(() => {
        cleanup()
    })

    // The save writes the feature flag directly, so editor access to the experiment says
    // nothing about it.
    it.each([
        [AccessControlLevel.Viewer, true],
        [AccessControlLevel.Editor, false],
    ])('flag access %s blocks the save: %s', async (userAccessLevel, blocked) => {
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

    it('names the feature flag as the blocked resource', async () => {
        useMocks(mocksFor(AccessControlLevel.Viewer))
        renderModal(AccessControlLevel.Viewer)

        await waitFor(() => expect(screen.getByText('Save').closest('button')).toHaveAttribute('aria-disabled'))
        await userEvent.hover(screen.getByText('Save'))

        // The 403 the save used to return says only "this resource", which left the user with no
        // way to tell the flag apart from the experiment they do have access to.
        await waitFor(() => expect(screen.getByText(/permissions for this feature flag/)).toBeInTheDocument())
    })
})
