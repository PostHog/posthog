import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { ErrorTrackingStackFrameRecord } from '../types'
import { stackFrameLogic } from './stackFrameLogic'

describe('stackFrameLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        [
            'loadFromRawIds',
            'stackFrames',
            (logic: ReturnType<typeof stackFrameLogic.build>) => logic.actions.loadFromRawIds(['raw-1']),
        ],
        [
            'loadForSymbolSet',
            'symbolSetStackFrames',
            (logic: ReturnType<typeof stackFrameLogic.build>) => logic.actions.loadForSymbolSet('symbol-set-1'),
        ],
    ] as const)('does not report a failure when %s resolves after unmount', async (_, apiMethod, load) => {
        let resolveRequest: (value: { results: ErrorTrackingStackFrameRecord[] }) => void = () => {}
        jest.spyOn(api.errorTracking, apiMethod).mockReturnValue(
            new Promise((resolve) => {
                resolveRequest = resolve
            })
        )
        const captureException = jest.spyOn(posthog, 'captureException').mockImplementation()
        const consoleError = jest.spyOn(console, 'error').mockImplementation()

        const logic = stackFrameLogic()
        const unmount = logic.mount()
        load(logic)
        unmount()

        resolveRequest({ results: [{ raw_id: 'raw-1' } as ErrorTrackingStackFrameRecord] })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(captureException).not.toHaveBeenCalled()
        expect(consoleError).not.toHaveBeenCalled()
    })
})
