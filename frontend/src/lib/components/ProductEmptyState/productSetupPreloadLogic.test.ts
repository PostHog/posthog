import { initKeaTests } from '~/test/init'

import { eventDefinitionsList } from 'products/event_definitions/frontend/generated/api'

import { productSetupPreloadLogic } from './productSetupPreloadLogic'

jest.mock('products/event_definitions/frontend/generated/api', () => ({
    eventDefinitionsList: jest.fn().mockResolvedValue({ results: [] }),
}))

describe('productSetupPreloadLogic', () => {
    beforeEach(() => {
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
})
