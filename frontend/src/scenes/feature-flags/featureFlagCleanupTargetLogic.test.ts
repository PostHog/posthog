import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { featureFlagCleanupTargetLogic } from './featureFlagCleanupTargetLogic'

describe('featureFlagCleanupTargetLogic', () => {
    beforeEach(silenceKeaLoadersErrors)
    afterEach(resumeKeaLoadersErrors)

    it.each([
        [403, 'PostHog Desktop access is required. Contact your organization admin.'],
        [503, 'Could not check which repositories are connected. Try again.'],
    ])('explains a %s lookup failure and clears it on retry', async (status, expectedError) => {
        useMocks({
            get: {
                '/api/projects/:projectId/feature_flags/1/cleanup_target/': [
                    status,
                    { error: 'PostHog Desktop access is required. Contact your organization admin.' },
                ],
            },
        })
        initKeaTests()
        const logic = featureFlagCleanupTargetLogic({ featureFlagId: 1 })
        logic.mount()
        logic.actions.loadCleanupTarget()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.cleanupTargetFailed).toBe(true)
        expect(logic.values.cleanupTargetError).toBe(expectedError)

        useMocks({
            get: {
                '/api/projects/:projectId/feature_flags/1/cleanup_target/': {
                    repository: 'example/app',
                    source: 'single_repo',
                    candidates: ['example/app'],
                },
            },
        })
        logic.actions.loadCleanupTarget()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.cleanupTargetFailed).toBe(false)
        expect(logic.values.cleanupTargetError).toBeNull()
        expect(logic.values.cleanupTarget?.repository).toBe('example/app')
        logic.unmount()
    })
})
