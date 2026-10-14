import { initKeaTests } from '~/test/init'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

import { productSetupPreloadLogic } from './productSetupPreloadLogic'

jest.mock('products/event_definitions/frontend/generated/api', () => ({
    eventDefinitionsList: jest.fn().mockResolvedValue({ results: [] }),
}))

describe('productSetupPreloadLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    // The authenticated shell mounts after the team has loaded, so no team listener fires. Waiting
    // for idle there lets a gated scene open on its own spinner before the preload answers.
    it('preloads at mount when the team is already known, without waiting for idle', () => {
        productSetupPreloadLogic.mount()

        expect(eventDefinitionsList).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['is still running', (): Promise<never> => new Promise(() => {}), 1],
        ['failed', (): Promise<never> => Promise.reject(new Error('offline')), 2],
    ])('sends the idle retry only if the mount request failed, not when it %s', async (_, response, calls) => {
        jest.mocked(eventDefinitionsList).mockImplementationOnce(response)

        productSetupPreloadLogic.mount()
        await jest.runOnlyPendingTimersAsync()

        expect(eventDefinitionsList).toHaveBeenCalledTimes(calls)
    })
})
