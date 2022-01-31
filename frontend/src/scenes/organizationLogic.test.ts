import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { mockAPI, MOCK_DEFAULT_ORGANIZATION } from '../lib/api.mock'
import { AppContext } from '../types'
import { organizationLogic } from './organizationLogic'

jest.mock('lib/api')

describe('organizationLogic', () => {
    let logic: ReturnType<typeof organizationLogic.build>

    mockAPI()

    describe('if POSTHOG_APP_CONTEXT available', () => {
        beforeEach(() => {
            window.POSTHOG_APP_CONTEXT = { current_user: { organization: { id: 'WXYZ' } } } as unknown as AppContext
        })

        initKeaTestLogic({
            logic: organizationLogic,
            onLogic: (l) => {
                logic = l
            },
        })

        it('loads organization from window', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['loadCurrentOrganization'])
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: { id: 'WXYZ' },
            })
        })
    })

    describe('if POSTHOG_APP_CONTEXT not available', () => {
        initKeaTestLogic({
            logic: organizationLogic,
            onLogic: (l) => {
                logic = l
            },
        })

        it('loads organization from API', async () => {
            await expectLogic(logic).toDispatchActions(['loadCurrentOrganization', 'loadCurrentOrganizationSuccess'])
            await expectLogic(logic).toMatchValues({
                currentOrganization: {
                    available_features: [],
                    ...MOCK_DEFAULT_ORGANIZATION,
                },
            })
        })
    })
})
