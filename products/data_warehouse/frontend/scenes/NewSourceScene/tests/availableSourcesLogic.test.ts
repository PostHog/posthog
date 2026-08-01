import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { availableSourcesLogic } from '../availableSourcesLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        externalDataSources: {
            wizard: jest.fn(),
        },
    },
}))

describe('availableSourcesLogic', () => {
    let logic: ReturnType<typeof availableSourcesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = availableSourcesLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['a 403', { status: 403 }, 'forbidden'],
        ['a 500', { status: 500 }, 'unknown'],
        ['a network failure with no status', { status: undefined }, 'unknown'],
    ])(
        // Regression test: the logic used to only special-case 403, so a 500 (the sources-page
        // outage) and a permissions denial were indistinguishable to the banner that reads this.
        'sets availableSourcesError to %s for %s, without surfacing loader failure',
        async (_label, error, expectedErrorType) => {
            jest.spyOn(api.externalDataSources, 'wizard').mockRejectedValue(error)

            // Mounting triggers the logic's own afterMount load — set the mock before mounting so
            // that first automatic load is the one under test.
            await expectLogic(logic, () => {
                logic.mount()
            })
                .toDispatchActions(['load', 'loadSuccess'])
                .toNotHaveDispatchedActions(['loadFailure'])
                .toMatchValues({
                    availableSources: null,
                    availableSourcesError: expectedErrorType,
                })
        }
    )

    it('clears availableSourcesError on a successful reload', async () => {
        jest.spyOn(api.externalDataSources, 'wizard').mockRejectedValueOnce({ status: 500 })

        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['load', 'loadSuccess'])
            .toMatchValues({ availableSourcesError: 'unknown' })

        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValueOnce({ postgres: {} } as any)

        await expectLogic(logic, () => {
            logic.actions.load()
        })
            .toDispatchActions(['load', 'loadSuccess'])
            .toMatchValues({ availableSourcesError: null })
    })
})
