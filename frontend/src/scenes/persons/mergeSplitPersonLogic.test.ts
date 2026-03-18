import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mergeSplitPersonLogic } from './mergeSplitPersonLogic'
import { personsLogic } from './personsLogic'

const URL_DISTINCT_ID = 'user@example.com'

const MOCK_PERSON = {
    id: '123',
    uuid: 'abc-123',
    distinct_ids: [URL_DISTINCT_ID, 'user-456'],
    properties: { email: 'user@example.com' },
    created_at: '2024-01-01T00:00:00Z',
}

describe('mergeSplitPersonLogic', () => {
    let logic: ReturnType<typeof mergeSplitPersonLogic.build>
    let personsLogicInstance: ReturnType<typeof personsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/persons/': { results: [MOCK_PERSON], count: 1 },
            },
            post: {
                '/api/person/123/split/': { success: true },
            },
        })
        initKeaTests()

        personsLogicInstance = personsLogic({ syncWithUrl: true, urlId: URL_DISTINCT_ID })
        personsLogicInstance.mount()

        logic = mergeSplitPersonLogic({ person: MOCK_PERSON, urlId: URL_DISTINCT_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        personsLogicInstance.unmount()
    })

    describe('cancel', () => {
        it('closes the modal by dispatching setSplitMergeModalShown(false) on the correct personsLogic instance', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: true,
            })

            await expectLogic(logic, () => {
                logic.actions.cancel()
            })
                .toDispatchActions([personsLogicInstance.actionTypes.setSplitMergeModalShown])
                .toFinishListeners()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: false,
            })
        })

        it('does not close the modal while execute is loading', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)

            logic.actions.execute()
            logic.actions.cancel()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: true,
            })
        })
    })

    describe('execute', () => {
        it('closes the modal on successful split', async () => {
            personsLogicInstance.actions.setSplitMergeModalShown(true)

            await expectLogic(logic, () => {
                logic.actions.execute()
            })
                .toDispatchActions(['execute', 'executeSuccess'])
                .toFinishListeners()

            await expectLogic(personsLogicInstance).toMatchValues({
                splitMergeModalShown: false,
            })
        })
    })

    describe('urlId matching', () => {
        it('connects to the correct personsLogic instance based on urlId', async () => {
            const differentPersonsLogic = personsLogic({ syncWithUrl: true, urlId: 'different-user' })
            differentPersonsLogic.mount()
            differentPersonsLogic.actions.setSplitMergeModalShown(true)

            logic.actions.cancel()

            await expectLogic(differentPersonsLogic).toMatchValues({
                splitMergeModalShown: true,
            })

            differentPersonsLogic.unmount()
        })
    })
})
