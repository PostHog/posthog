import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { batchExportBackfillsLogic } from '../../data-pipelines/batch-exports/batchExportBackfillsLogic'

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
        success: jest.fn(),
        info: jest.fn(),
        warning: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

const MOCK_BATCH_EXPORT_ID = 'batch-export-from-hog-function'

describe('hogFunctionBackfillsLogic', () => {
    describe('batchExportBackfillsLogic mounting without batchExportConfigFormLogic', () => {
        it('fails when batchExportBackfillsLogic is mounted without pre-mounting batchExportConfigFormLogic', async () => {
            // oxlint-disable-next-line react-hooks/rules-of-hooks -- useMocks is not a React hook
            useMocks({
                get: {
                    [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/`]: {
                        id: MOCK_BATCH_EXPORT_ID,
                        team_id: 997,
                        name: 'Test Export',
                        destination: { type: 'S3', config: {} },
                        interval: 'hour',
                        paused: false,
                        model: 'events',
                        filters: [],
                    },
                    '/api/environments/:team_id/batch_exports/test/': { steps: [] },
                    [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                        results: [],
                        next: null,
                    },
                },
            })
            initKeaTests()
            await expectLogic(teamLogic).toFinishAllListeners()

            // This reproduces the error seen in HogFunctionBackfills:
            // batchExportBackfillsLogic connects to batchExportConfigFormLogic,
            // but batchExportConfigFormLogic hasn't been mounted by any parent BindLogic.
            // In the BatchExportScene this works because BindLogic mounts it first.
            //
            // The error is thrown during the kea build/mount chain. We catch it
            // to verify the exact failure mode.
            let caughtError: Error | null = null
            try {
                const logic = batchExportBackfillsLogic({ id: MOCK_BATCH_EXPORT_ID })
                logic.mount()
            } catch (e) {
                caughtError = e as Error
            }

            expect(caughtError).not.toBeNull()
            expect(caughtError!.message).toMatch(/Can not find path.*batchExportConfigFormLogic/)
        })
    })
})
