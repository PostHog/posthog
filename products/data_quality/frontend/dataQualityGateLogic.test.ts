import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataWarehouseDataQualityGatePartialUpdate,
    dataWarehouseDataQualityGateRetrieve,
} from 'products/data_warehouse/frontend/generated/api'

import { dataQualityGateLogic } from './dataQualityGateLogic'

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        constructor(message?: string, status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
        }
    }
    return {
        __esModule: true,
        default: {},
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseDataQualityGateRetrieve: jest.fn(),
    dataWarehouseDataQualityGatePartialUpdate: jest.fn(),
}))

describe('dataQualityGateLogic', () => {
    let logic: ReturnType<typeof dataQualityGateLogic.build>

    async function mountLogic(): Promise<void> {
        initKeaTests()
        logic = dataQualityGateLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        jest.clearAllMocks()
        silenceKeaLoadersErrors()
        ;(dataWarehouseDataQualityGateRetrieve as jest.Mock).mockResolvedValue({
            gate_materialization_on_checks: false,
        })
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        logic?.unmount()
    })

    it('hides the toggle when the setting cannot be read', async () => {
        const { ApiError } = jest.requireMock('lib/api')
        ;(dataWarehouseDataQualityGateRetrieve as jest.Mock).mockRejectedValue(new ApiError('Forbidden', 403))

        await mountLogic()

        expect(logic.values.gateReadable).toBe(false)
        expect(logic.values.gateConfig).toBeNull()
    })

    it('snaps the switch back when the write is refused', async () => {
        const { ApiError } = jest.requireMock('lib/api')
        ;(dataWarehouseDataQualityGatePartialUpdate as jest.Mock).mockRejectedValue(
            new ApiError('Forbidden', 403, undefined, { detail: 'You need editor access.' })
        )
        await mountLogic()

        logic.actions.setGateEnabled(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.gateConfig?.gate_materialization_on_checks).toBe(false)
        expect(lemonToast.error).toHaveBeenCalledWith('You need editor access.')
    })

    it('locks the toggle while a write is in flight and adopts the stored value', async () => {
        let resolvePatch!: (value: { gate_materialization_on_checks: boolean }) => void
        ;(dataWarehouseDataQualityGatePartialUpdate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                resolvePatch = resolve
            })
        )
        await mountLogic()

        logic.actions.setGateEnabled(true)
        // The switch is disabled via this flag until the PATCH settles, so a second click cannot
        // start an overlapping write.
        expect(logic.values.gateSaving).toBe(true)

        resolvePatch({ gate_materialization_on_checks: true })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.gateSaving).toBe(false)
        expect(logic.values.gateConfig?.gate_materialization_on_checks).toBe(true)
    })
})
