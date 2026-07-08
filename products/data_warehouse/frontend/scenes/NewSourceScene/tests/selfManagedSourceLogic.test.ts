import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { selfManagedSourceLogic } from '../selfManagedSourceLogic'

describe('selfManagedSourceLogic', () => {
    let logic: ReturnType<typeof selfManagedSourceLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = selfManagedSourceLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('validates a table with a null credential without crashing', async () => {
        // Self-managed sources stored without a credential come back as credential: null;
        // computing validation errors must not throw a TypeError on the missing object.
        await expectLogic(logic, () => {
            logic.actions.setTableValues({ credential: null })
        }).toMatchValues({
            tableValidationErrors: expect.objectContaining({
                credential: {
                    access_secret: 'Please enter an access secret.',
                    access_key: 'Please enter an access key.',
                },
            }),
        })
    })
})
