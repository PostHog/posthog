import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { experimentsFlagCleanupTargetRetrieve } from 'products/experiments/frontend/generated/api'

import { modalsLogic } from '../modalsLogic'
import { flagCleanupTargetLogic } from './flagCleanupTargetLogic'

jest.mock('products/experiments/frontend/generated/api', () => ({
    experimentsFlagCleanupTargetRetrieve: jest.fn(),
}))

const mockRetrieve = experimentsFlagCleanupTargetRetrieve as jest.Mock

describe('flagCleanupTargetLogic', () => {
    beforeEach(() => {
        initKeaTests()
        mockRetrieve.mockReset()
    })

    it('loads the target when the finish modal opens, only for users with the cleanup feature', async () => {
        mockRetrieve.mockResolvedValue({ repository: null, source: 'ambiguous', candidates: ['acme/web', 'acme/api'] })
        featureFlagLogic.mount()
        const logic = flagCleanupTargetLogic({ experimentId: 1 })
        logic.mount()

        // Cleanup flags off: opening the modal must not hit the endpoint (it would 403).
        modalsLogic.mount()
        modalsLogic.actions.openFinishExperimentModal()
        await Promise.resolve()
        expect(mockRetrieve).not.toHaveBeenCalled()

        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.EXPERIMENT_FLAG_CLEANUP_PR]: true,
            [FEATURE_FLAGS.TASKS]: true,
        })
        modalsLogic.actions.openFinishExperimentModal()
        await Promise.resolve()
        expect(mockRetrieve).toHaveBeenCalledTimes(1)
        await Promise.resolve()
        expect(logic.values.cleanupTarget?.candidates).toEqual(['acme/web', 'acme/api'])
    })
})
