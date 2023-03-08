import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { billingLogic, BillingAlertType } from '~/scenes/billing/billingLogic'
import { useMocks } from '~/mocks/jest'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PlanInterface, BillingType } from '~/types'
import { router } from 'kea-router'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'
import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'

const PLANS: PlanInterface[] = [
    {
        key: 'standard',
        name: 'Payed Plan',
        custom_setup_billing_message: 'Hello world, time to pay',
        image_url: 'https://example.com/image.png',
        self_serve: true,
        is_metered_billing: true,
        event_allowance: 1000000,
        price_string: "Free until it isn't",
    },
    {
        key: 'amazing',
        name: 'Amazing Payed Plan',
        custom_setup_billing_message: 'Hello world, time to pay',
        image_url: 'https://example.com/image.png',
        self_serve: true,
        is_metered_billing: true,
        event_allowance: 1000000,
        price_string: "Free until it isn't",
    },
]

const BILLING_NO_PLAN: BillingType = {
    should_setup_billing: false,
    is_billing_active: false,
    plan: null,
    billing_period_ends: null,
    event_allocation: 1000000,
    current_usage: 900000,
    subscription_url: 'https://testserver/organization/billing/subscribe',
    current_bill_amount: null,
    current_bill_usage: null,
    should_display_current_bill: false,
    billing_limit: null,
    billing_limit_exceeded: false,
    current_bill_cycle: null,
    tiers: null,
}

const BILLING_LIMIT_EXCEEDED = { ...BILLING_NO_PLAN, billing_limit_exceeded: true }

const BILLING_SHOULD_SETUP: BillingType = {
    should_setup_billing: true,
    is_billing_active: false,
    plan: PLANS[0],
    billing_period_ends: null,
    event_allocation: 1000000,
    current_usage: 100000,
    subscription_url: 'https://testserver/organization/billing/subscribe',
    current_bill_amount: null,
    current_bill_usage: null,
    should_display_current_bill: false,
    billing_limit: null,
    billing_limit_exceeded: false,
    current_bill_cycle: null,
    tiers: null,
}

const BILLING_CUSTOMER: BillingType = {
    should_setup_billing: false,
    is_billing_active: true,
    plan: PLANS[1],
    billing_period_ends: '2021-06-30T00:00:00Z',
    event_allocation: 1000000,
    current_usage: 950000,
    subscription_url: 'https://testserver/organization/billing/subscribe',
    current_bill_amount: 10,
    current_bill_usage: 950000,
    should_display_current_bill: true,
    billing_limit: 1000000,
    billing_limit_exceeded: false,
    current_bill_cycle: {
        current_period_start: 1622540800000,
        current_period_end: 1622540800000,
    },
    tiers: [
        {
            name: 'first tier',
            price_per_event: 0,
            number_of_events: 0,
            subtotal: 0,
            running_total: 0,
        },
    ],
}

// eslint-disable-next-line @typescript-eslint/explicit-function-return-type
const mockBilling = (billing: BillingType) => {
    useMocks({
        get: {
            '/api/billing': billing,
        },
    })
}

describe('billingLogic', () => {
    let logic: ReturnType<typeof billingLogic.build>

    beforeEach(async () => {
        jest.spyOn(URLSearchParams.prototype, 'get').mockImplementation((key) => key)
        jest.spyOn(api, 'get')
        useMocks({
            get: {
                '/api/plans': { results: PLANS },
                '/api/billing-v2/': () => [404, {}],
            },
        })
        initKeaTests()
        silenceKeaLoadersErrors()
        logic = billingLogic()
        logic.mount()
        await expectLogic(logic).toMount([featureFlagLogic, eventUsageLogic])
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
    })

    it('loads billing and plans for user without a plan', async () => {
        mockBilling(BILLING_NO_PLAN)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                billing: BILLING_NO_PLAN,
                plans: PLANS,
            })
    })

    it('loads billing and plan for customer', async () => {
        mockBilling(BILLING_CUSTOMER)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                billing: BILLING_CUSTOMER,
                plans: [PLANS[1]],
            })
    })

    it('calculates percentages correctly', async () => {
        mockBilling(BILLING_NO_PLAN)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                percentage: 0.9,
                strokeColor: 'var(--danger)',
            })

        mockBilling(BILLING_SHOULD_SETUP)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                percentage: 0.1,
                strokeColor: 'var(--primary)',
            })

        mockBilling(BILLING_CUSTOMER)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                percentage: 0.95,
                strokeColor: 'var(--danger)',
            })
    })

    it('triggers the right alerts', async () => {
        mockBilling(BILLING_SHOULD_SETUP)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                alertToShow: BillingAlertType.SetupBilling,
            })

        mockBilling(BILLING_LIMIT_EXCEEDED)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                alertToShow: BillingAlertType.UsageLimitExceeded,
            })

        mockBilling(BILLING_CUSTOMER)
        await expectLogic(logic, () => {
            logic.actions.loadBilling()
        })
            .toFinishAllListeners()
            .toMatchValues({
                alertToShow: BillingAlertType.UsageNearLimit,
            })
    })
    it('reports that billing has been cancelled during onboarding', async () => {
        router.actions.push('/ingestion/billing?reason=cancelled')
        await expectLogic(logic).toDispatchActions(['reportIngestionBillingCancelled'])
    })
    it('correctly sets redirect depending on flow', async () => {
        // onboarding flow
        router.actions.push('/organization/billing/subscribed?s=success&referer=ingestion')
        await expectLogic(logic)
            .toDispatchActions([logic.actionCreators.referer('ingestion')])
            .toMatchValues({
                billingSuccessRedirect: urls.events(),
            })
        // onboarding flow
        router.actions.push('/organization/billing/subscribed?s=success&referer=billing')
        await expectLogic(logic)
            .toDispatchActions([logic.actionCreators.referer('billing')])
            .toMatchValues({
                billingSuccessRedirect: urls.projectHomepage(),
            })
    })
})
