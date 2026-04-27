import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { hogFunctionBackfillsLogic } from './hogFunctionBackfillsLogic'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    hogFunctions: {
        get: jest.fn(),
        getTemplate: jest.fn(),
        update: jest.fn(),
        create: jest.fn(),
        enableBackfills: jest.fn(),
    },
}))

jest.mock('lib/utils/product-intents', () => ({
    addProductIntent: jest.fn().mockResolvedValue(null),
}))

const mockApi = api.hogFunctions as jest.Mocked<typeof api.hogFunctions>

const MOCK_HOG_FUNCTION_ID = 'hog-func-001'
const MOCK_BATCH_EXPORT_ID = 'batch-export-from-hog-func'

function makeHogFunction(overrides: Partial<HogFunctionType> = {}): HogFunctionType {
    return {
        id: MOCK_HOG_FUNCTION_ID,
        type: 'destination',
        name: 'Test Destination',
        description: '',
        created_at: '2024-01-01T00:00:00Z',
        created_by: {} as any,
        updated_at: '2024-01-01T00:00:00Z',
        enabled: true,
        hog: '',
        inputs_schema: [],
        inputs: {},
        filters: {},
        icon_url: null,
        template: null,
        masking: null,
        ...overrides,
    } as HogFunctionType
}

describe('hogFunctionBackfillsLogic', () => {
    let logic: ReturnType<typeof hogFunctionBackfillsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it('calls enableHogFunctionBackfills when batch_export_id is missing', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockResolvedValue({} as any)

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockApi.enableBackfills).toHaveBeenCalledWith(MOCK_HOG_FUNCTION_ID)
    })

    it('does not call enableHogFunctionBackfills when batch_export_id is already set', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction({ batch_export_id: MOCK_BATCH_EXPORT_ID }))

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockApi.enableBackfills).not.toHaveBeenCalled()
    })

    it('does not throw when enableBackfills API fails', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockRejectedValue(new Error('Network error'))

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['enableHogFunctionBackfills']).toFinishAllListeners()

        // The error is caught gracefully — logic stays mounted and isn't in a broken state
        expect(mockApi.enableBackfills).toHaveBeenCalled()
        expect(logic.isMounted()).toBeTruthy()
    })
})
