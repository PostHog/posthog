/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { OrganizationMembershipLevel } from 'lib/constants'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType, OrganizationType, StartupProgramLabel } from '~/types'

import { StartupProgramType, startupProgramLogic } from './startupProgramLogic'

jest.mock('posthog-js')

const blockedEvents = (): any[] =>
    (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === 'startup program application blocked')

const seedBilling = async (billing: Partial<BillingType> = {}): Promise<void> => {
    useMocks({
        get: {
            '/api/billing': () => [
                200,
                {
                    ...billingJson,
                    startup_program_label: null,
                    startup_program_label_previous: null,
                    is_annual_plan_customer: false,
                    ...billing,
                },
            ],
        },
    })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

const initStartupProgramTest = ({
    email = 'founder@gmail.com',
    organization = MOCK_DEFAULT_ORGANIZATION,
}: {
    email?: string
    organization?: OrganizationType
} = {}): void => {
    initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, organization)
    userLogic.mount()
    userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, email, organization })
}

const mountStartupProgramLogic = async ({
    billing = {},
    email = 'founder@gmail.com',
    organization = MOCK_DEFAULT_ORGANIZATION,
    referrer,
}: {
    billing?: Partial<BillingType>
    email?: string
    organization?: OrganizationType
    referrer?: string
} = {}): Promise<ReturnType<typeof startupProgramLogic.build>> => {
    initStartupProgramTest({ email, organization })
    await seedBilling(billing)
    ;(posthog.capture as jest.Mock).mockClear()

    const logic = startupProgramLogic({ referrer })
    logic.mount()
    return logic
}

describe('startupProgramLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('captures a blocked form event when the company-email gate is shown', async () => {
        await mountStartupProgramLogic()

        expect(blockedEvents()).toEqual([
            [
                'startup program application blocked',
                {
                    email_domain: 'gmail.com',
                    program: StartupProgramType.Startup,
                    organization_id: MOCK_DEFAULT_ORGANIZATION.id,
                    blocked_at: 'form',
                },
            ],
        ])
    })

    it('captures when the company-email gate becomes visible after billing loads', async () => {
        initStartupProgramTest()
        ;(posthog.capture as jest.Mock).mockClear()

        const logic = startupProgramLogic()
        logic.mount()

        expect(logic.values.shouldShowEmailDomainBlockedGate).toBe(false)
        expect(blockedEvents()).toHaveLength(0)

        await seedBilling()

        expect(logic.values.shouldShowEmailDomainBlockedGate).toBe(true)
        expect(blockedEvents()).toEqual([
            [
                'startup program application blocked',
                expect.objectContaining({
                    blocked_at: 'form',
                    email_domain: 'gmail.com',
                }),
            ],
        ])
    })

    it.each([
        [
            'current startup program gate',
            MOCK_DEFAULT_ORGANIZATION,
            { startup_program_label: StartupProgramLabel.Startup },
        ],
        [
            'previous startup program gate',
            MOCK_DEFAULT_ORGANIZATION,
            { startup_program_label_previous: StartupProgramLabel.Startup },
        ],
        ['annual-plan gate', MOCK_DEFAULT_ORGANIZATION, { is_annual_plan_customer: true }],
        ['permission gate', { ...MOCK_DEFAULT_ORGANIZATION, membership_level: OrganizationMembershipLevel.Member }, {}],
    ])('does not capture when the %s is shown instead', async (_, organization, billing) => {
        const logic = await mountStartupProgramLogic({
            organization: organization as OrganizationType,
            billing: billing as Partial<BillingType>,
        })

        expect(logic.values.isEmailDomainBlocked).toBe(true)
        expect(blockedEvents()).toHaveLength(0)
    })

    it('captures the YC program when a previous startup-program user can reapply on the YC page', async () => {
        await mountStartupProgramLogic({
            billing: { startup_program_label_previous: StartupProgramLabel.Startup },
            referrer: 'yc',
        })

        expect(blockedEvents()).toEqual([
            [
                'startup program application blocked',
                expect.objectContaining({
                    blocked_at: 'form',
                    program: StartupProgramType.YC,
                }),
            ],
        ])
    })

    describe('YC verification link', () => {
        // The billing service verifies the link once, on submit. Client-side we only check the URL shape.
        it('requires a link on the YC form and validates its shape', async () => {
            const logic = await mountStartupProgramLogic({ email: 'founder@posthog.com', referrer: 'yc' })

            expect(logic.values.startupProgramValidationErrors.yc_verification_url).toEqual(
                'Please enter your YC verification link'
            )

            logic.actions.setStartupProgramValue('yc_verification_url', 'https://example.com/verify/abc')
            expect(logic.values.startupProgramValidationErrors.yc_verification_url).toEqual(
                'This should look like https://www.ycombinator.com/verify/your-unique-code'
            )

            logic.actions.setStartupProgramValue(
                'yc_verification_url',
                'https://www.ycombinator.com/verify/db9imrf5u1kaxib5'
            )
            expect(logic.values.startupProgramValidationErrors.yc_verification_url).toBeUndefined()
        })

        it('does not require a link on the non-YC form', async () => {
            const logic = await mountStartupProgramLogic({ email: 'founder@posthog.com' })

            expect(logic.values.startupProgramValidationErrors.yc_verification_url).toBeUndefined()
        })
    })
})
