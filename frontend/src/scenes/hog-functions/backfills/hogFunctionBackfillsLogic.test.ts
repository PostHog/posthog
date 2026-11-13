import { MOCK_TEAM_ID } from 'lib/api.mock'

import { render, screen } from '@testing-library/react'
import { expectLogic, partial } from 'kea-test-utils'
import { createElement } from 'react'
import { ToastContainer } from 'react-toastify'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { HogFunctionType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import { hogFunctionBackfillsLogic } from './hogFunctionBackfillsLogic'

// Mock only the hogFunctions namespace on the default api export — replacing the module
// object wholesale would leave `api.query` & co undefined for connected logics
jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')
    return {
        ...actual,
        __esModule: true,
        default: {
            ...actual.default,
            hogFunctions: {
                get: jest.fn(),
                getTemplate: jest.fn(),
                update: jest.fn(),
                create: jest.fn(),
                enableBackfills: jest.fn(),
            },
        },
    }
})

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

    it('shows an error after a failed enable, then opens backfills with unsaved edits kept when trying again succeeds', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockRejectedValueOnce(new Error('Network error'))
        const configurationLogic = hogFunctionConfigurationLogic({ id: MOCK_HOG_FUNCTION_ID })
        configurationLogic.mount()
        await expectLogic(configurationLogic).toFinishAllListeners()
        configurationLogic.actions.setConfigurationValues({ name: 'Edited destination' })

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ isReady: false, enableBackfillsFailed: true })

        const enabledHogFunction = makeHogFunction({ batch_export_id: MOCK_BATCH_EXPORT_ID })
        mockApi.enableBackfills.mockResolvedValueOnce({} as any)
        mockApi.get.mockResolvedValue(enabledHogFunction)
        useMocks({
            get: { [`/api/projects/${MOCK_TEAM_ID}/hog_functions/${MOCK_HOG_FUNCTION_ID}/`]: enabledHogFunction },
        })
        await expectLogic(logic, () => {
            logic.actions.enableHogFunctionBackfills()
        })
            .toFinishAllListeners()
            .toMatchValues({
                isReady: true,
                enableBackfillsFailed: false,
                configuration: partial({ name: 'Edited destination', batch_export_id: MOCK_BATCH_EXPORT_ID }),
            })
    })

    it('sends one enable request when trying again is pressed twice', async () => {
        let enableRequests = 0
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockImplementation(jest.requireActual('lib/api').default.hogFunctions.enableBackfills)
        useMocks({
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/hog_functions/${MOCK_HOG_FUNCTION_ID}/enable_backfills/`]: () => {
                    enableRequests += 1
                    return [403, { detail: 'Backfilling Workflows is not enabled for this team.' }]
                },
            },
        })

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ enableBackfillsFailed: true })

        await expectLogic(logic, () => {
            logic.actions.enableHogFunctionBackfills()
            logic.actions.enableHogFunctionBackfills()
        }).toFinishAllListeners()

        expect(enableRequests).toBe(2)
    })

    it('opens backfills when an enable that reported failure went through on the server', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockRejectedValue(new Error('Network error'))
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/hog_functions/${MOCK_HOG_FUNCTION_ID}/`]: makeHogFunction({
                    batch_export_id: MOCK_BATCH_EXPORT_ID,
                }),
            },
        })

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ isReady: true, enableBackfillsFailed: false, configurationChanged: false })
    })

    it('keeps unsaved configuration edits when enabling fails', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockRejectedValue(new Error('Network error'))
        const configurationLogic = hogFunctionConfigurationLogic({ id: MOCK_HOG_FUNCTION_ID })
        configurationLogic.mount()
        await expectLogic(configurationLogic).toFinishAllListeners()
        configurationLogic.actions.setConfigurationValues({ name: 'Edited destination' })

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ enableBackfillsFailed: true, configuration: partial({ name: 'Edited destination' }) })
    })

    it('keeps unsaved edits when a failed enable went through and reloading fails, and clearing them keeps backfills open', async () => {
        const enabledHogFunction = makeHogFunction({ batch_export_id: MOCK_BATCH_EXPORT_ID })
        mockApi.get
            .mockResolvedValueOnce(makeHogFunction({ batch_export_id: null }))
            .mockRejectedValue(new Error('Network error'))
        mockApi.enableBackfills.mockRejectedValue(new Error('Network error'))
        useMocks({
            get: { [`/api/projects/${MOCK_TEAM_ID}/hog_functions/${MOCK_HOG_FUNCTION_ID}/`]: enabledHogFunction },
        })
        const configurationLogic = hogFunctionConfigurationLogic({ id: MOCK_HOG_FUNCTION_ID })
        configurationLogic.mount()
        await expectLogic(configurationLogic).toFinishAllListeners()
        configurationLogic.actions.setConfigurationValues({ name: 'Edited destination' })

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                isReady: true,
                enableBackfillsFailed: false,
                configuration: partial({ name: 'Edited destination', batch_export_id: MOCK_BATCH_EXPORT_ID }),
            })
        await expectLogic(configurationLogic).toMatchValues({ unsavedConfiguration: null })

        await expectLogic(logic, () => {
            configurationLogic.actions.resetForm()
        })
            .toFinishAllListeners()
            .toMatchValues({ isReady: true, configuration: partial({ name: 'Test Destination' }) })
    })

    it('does not call enableHogFunctionBackfills when batch_export_id is already set', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction({ batch_export_id: MOCK_BATCH_EXPORT_ID }))

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(mockApi.enableBackfills).not.toHaveBeenCalled()
    })

    it('shows an error when enabling fails, then opens backfills once a reload brings the batch export', async () => {
        mockApi.get.mockResolvedValue(makeHogFunction())
        mockApi.enableBackfills.mockRejectedValue(new Error('Network error'))

        logic = hogFunctionBackfillsLogic({ id: MOCK_HOG_FUNCTION_ID })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        render(createElement(ToastContainer))
        await screen.findByText('Failed to enable backfills for this destination.')

        mockApi.get.mockResolvedValue(makeHogFunction({ batch_export_id: MOCK_BATCH_EXPORT_ID }))
        hogFunctionConfigurationLogic({ id: MOCK_HOG_FUNCTION_ID }).actions.loadHogFunction()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ isReady: true, enableBackfillsFailed: false })
    })
})
