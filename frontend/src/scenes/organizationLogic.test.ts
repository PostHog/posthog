import { BuiltLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { defaultAPIMocks, mockAPI } from '../lib/api.mock'
import { AppContext } from '../types'
import { organizationLogic, OrganizationUpdatePayload } from './organizationLogic'
import { organizationLogicType } from './organizationLogicType'

jest.mock('lib/api')

describe('organizationLogic', () => {
    let logic: BuiltLogic<organizationLogicType<OrganizationUpdatePayload>>

    mockAPI(async (url) => {
        return defaultAPIMocks(url)
    })

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
                currentOrganization: { id: 'ABCD' },
            })
        })
    })
})
