import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { batchExportBackfillsLogic } from '../../data-pipelines/batch-exports/batchExportBackfillsLogic'
import { batchExportConfigLogic } from '../../data-pipelines/batch-exports/batchExportConfigLogic'

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
    it('mounts correctly', async () => {
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
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                    results: [],
                    next: null,
                },
            },
        })
        initKeaTests()
        await expectLogic(teamLogic).toFinishAllListeners()

        // Pre-mount the lightweight batchExportConfigLogic, simulating what BindLogic
        // does in HogFunctionBackfills.tsx. This must happen before mounting
        // batchExportBackfillsLogic so the reducer is attached to the store.
        const configLogic = batchExportConfigLogic({ id: MOCK_BATCH_EXPORT_ID })
        configLogic.mount()
        await expectLogic(configLogic).toFinishAllListeners()

        const logic = batchExportBackfillsLogic({ id: MOCK_BATCH_EXPORT_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.batchExportConfig).toBeTruthy()
        expect(logic.values.batchExportConfig?.id).toBe(MOCK_BATCH_EXPORT_ID)
    })
})
