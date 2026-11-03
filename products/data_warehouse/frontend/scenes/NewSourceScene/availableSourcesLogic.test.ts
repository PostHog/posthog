import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { availableSourcesLogic } from './availableSourcesLogic'

jest.mock('lib/api')

describe('availableSourcesLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        [403, true],
        [500, false],
    ])('marks a %s from the wizard endpoint as forbidden: %s', async (status, forbidden) => {
        jest.spyOn(api.externalDataSources, 'wizard').mockRejectedValue({ status })

        const logic = availableSourcesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            availableSources: null,
            availableSourcesLoading: false,
            availableSourcesForbidden: forbidden,
        })
        logic.unmount()
    })

    it('clears forbidden when a later load succeeds', async () => {
        jest.spyOn(api.externalDataSources, 'wizard').mockRejectedValueOnce({ status: 403 })

        const logic = availableSourcesLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ availableSourcesForbidden: true })

        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValueOnce({} as any)
        logic.actions.load()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({ availableSourcesForbidden: false })
        logic.unmount()
    })
})
