import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { autoresearchNewLogic } from './autoresearchNewLogic'
import { autoresearchValidateCreate } from './generated/api'

jest.mock('./generated/api', () => ({
    autoresearchCreate: jest.fn(),
    autoresearchValidateCreate: jest.fn(),
}))

const mockValidate = autoresearchValidateCreate as jest.Mock

describe('autoresearchNewLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.useFakeTimers()
        initKeaTests()
        mockValidate.mockResolvedValue({ can_proceed: true, warnings: [] })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['a valid form', {}, 1],
        ['a cleared horizon', { horizon_days: NaN }, 0],
        ['a cleared training lookback', { training_lookback_days: NaN }, 0],
        ['a horizon out of range', { horizon_days: 0 }, 0],
        ['a fractional horizon', { horizon_days: 1.5 }, 0],
        ['a fractional training lookback', { training_lookback_days: 30.5 }, 0],
    ])('sends %s to the validate endpoint only when the day fields are valid', async (_, days, expectedCalls) => {
        const logic = autoresearchNewLogic()
        logic.mount()

        logic.actions.setNewPipelineValues({ target_event: '$pageview', ...days })
        await jest.advanceTimersByTimeAsync(1000)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockValidate).toHaveBeenCalledTimes(expectedCalls)
        expect(logic.values.validationFailed).toBe(false)
    })
})
