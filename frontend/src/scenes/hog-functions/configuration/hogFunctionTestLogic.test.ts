// The logic module reads the current team id at load time (persisted-reducer prefix); this keeps
// importing the pure helper below from throwing outside a mounted app context.
jest.mock('lib/utils/getAppContext', () => ({
    ...jest.requireActual('lib/utils/getAppContext'),
    getCurrentTeamId: () => 1,
}))

import { testInvocationErrorMessages } from './hogFunctionTestLogic'

describe('testInvocationErrorMessages', () => {
    it('reads the worker errors array from a non-200 response', () => {
        expect(
            testInvocationErrorMessages({ data: { status: 'error', errors: ['502 Bad Gateway'], logs: [] } })
        ).toEqual(['502 Bad Gateway'])
    })

    it('flattens a nested DRF validation payload into keyed messages', () => {
        expect(
            testInvocationErrorMessages({
                data: { configuration: { inputs: { url: ['This field is required.'] } } },
            })
        ).toEqual(['configuration.inputs.url: This field is required.'])
    })

    it('uses a string detail when that is all the response carries', () => {
        expect(testInvocationErrorMessages({ data: { detail: 'Not found' } })).toEqual(['Not found'])
    })

    it('falls back to the exception message when the response has no usable body', () => {
        expect(testInvocationErrorMessages({ message: 'Failed to fetch' })).toEqual(['Failed to fetch'])
    })
})
