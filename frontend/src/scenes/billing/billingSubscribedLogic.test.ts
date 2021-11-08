import { BuiltLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { router } from 'kea-router'
import { sceneLogic } from 'scenes/sceneLogic'
import { billingSubscribedLogicType } from './billingSubscribedLogicType'
import { billingSubscribedLogic, SubscriptionStatus } from './billingSubscribedLogic'
import { billingLogic } from './billingLogic'

jest.mock('lib/api')

describe('organizationLogic', () => {
    let logic: BuiltLogic<billingSubscribedLogicType<SubscriptionStatus>>

    mockAPI(async (url) => {
        return defaultAPIMocks(url)
    })

    describe('if subscription was successful', () => {
        initKeaTestLogic({
            logic: billingSubscribedLogic,
            onLogic: (l) => {
                logic = l
            },
        })

        it('mounts other logics', async () => {
            await expectLogic(logic).toMount([sceneLogic, billingLogic])
        })

        it('shows failed subscription by default', async () => {
            await expectLogic(logic).toNotHaveDispatchedActions(['setStatus', 'setSubscriptionId'])
            await expectLogic(logic).toMatchValues({
                status: 'failed',
            })
        })

        it('loads plan information and sets proper actions', async () => {
            router.actions.push('/organization/billing/subscribed', { s: 'success' })
            await expectLogic(logic).toDispatchActions(['setStatus'])
            await expectLogic(logic).toMatchValues({
                status: 'success',
                sessionId: null,
            })
            await expectLogic(logic).toNotHaveDispatchedActions(['setSessionId'])
        })

        it('loads failed page with session id', async () => {
            router.actions.push('/organization/billing/subscribed', { session_id: 'cs_test_12345678' })
            await expectLogic(logic).toDispatchActions(['setSessionId'])
            await expectLogic(logic).toMatchValues({
                status: 'failed',
                sessionId: 'cs_test_12345678',
                billing: null,
            })
            await expectLogic(logic).toNotHaveDispatchedActions(['setStatus'])
        })
    })
})
