import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { requestAiAccessCreate } from 'products/platform_features/frontend/generated/api'

import { aiConsentLogic } from './aiConsentLogic'

jest.mock('products/platform_features/frontend/generated/api', () => ({
    requestAiAccessCreate: jest.fn(),
}))

jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn() },
}))

describe('aiConsentLogic', () => {
    let logic: ReturnType<typeof aiConsentLogic.build>

    beforeEach(() => {
        // dataProcessingDismissed / aiAccessRequestedByOrg are persisted to localStorage, which jsdom
        // keeps alive across tests in this file — start each test from a clean slate.
        localStorage.clear()
        useMocks({
            patch: {
                '/api/organizations/:id': async ({ request }) => [
                    200,
                    {
                        ...MOCK_DEFAULT_ORGANIZATION,
                        ...((await request.json()) as Partial<typeof MOCK_DEFAULT_ORGANIZATION>),
                    },
                ],
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    describe('dataProcessingAccepted selector', () => {
        it.each([
            { approved: true, expected: true },
            { approved: false, expected: false },
        ])(
            'is $expected when the organization is_ai_data_processing_approved is $approved',
            ({ approved, expected }) => {
                initKeaTests(true, undefined, undefined, {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    is_ai_data_processing_approved: approved,
                })
                logic = aiConsentLogic()
                logic.mount()

                expect(logic.values.dataProcessingAccepted).toBe(expected)
            }
        )
    })

    describe('dataProcessingApprovalDisabledReason selector', () => {
        it.each([
            { level: OrganizationMembershipLevel.Admin, expected: null },
            { level: OrganizationMembershipLevel.Owner, expected: null },
            {
                level: OrganizationMembershipLevel.Member,
                expected: `Ask an admin or owner of ${MOCK_DEFAULT_ORGANIZATION.name} to approve this`,
            },
        ])('is $expected for membership level $level', ({ level, expected }) => {
            initKeaTests(true, undefined, undefined, { ...MOCK_DEFAULT_ORGANIZATION, membership_level: level })
            logic = aiConsentLogic()
            logic.mount()

            expect(logic.values.dataProcessingApprovalDisabledReason).toBe(expected)
        })
    })

    // Regression guard for the extraction: dismissal must persist under the exact
    // `posthog_ai_data_processing_dismissed_<YYYY-MM>` key the popover already relies on, or a user's
    // dismissal silently stops sticking across reloads.
    it('dismissDataProcessing marks the popover dismissed', async () => {
        initKeaTests()
        logic = aiConsentLogic()
        logic.mount()

        expect(logic.values.dataProcessingDismissed).toBe(false)
        logic.actions.dismissDataProcessing()
        expect(logic.values.dataProcessingDismissed).toBe(true)
    })

    it('acceptDataProcessing approves AI data processing for the current organization and toasts success', async () => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        logic = aiConsentLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.acceptDataProcessing()
        }).toFinishAllListeners()

        expect(logic.values.dataProcessingAccepted).toBe(true)
        expect(lemonToast.success).toHaveBeenCalledWith('AI data processing approved')
    })

    // Regression guard: approving consent can trigger a full-page SSO reauthentication redirect,
    // which discards any in-memory "resume this action" closure (see AIConsentPopoverWrapper). The
    // pending destination must survive that round trip via localStorage and resume once consent is
    // already granted on the next mount, rather than leaving the user on a blank landing state.
    describe('pendingApprovalRedirect', () => {
        it('persists across a logic remount under the expected storage key', () => {
            initKeaTests()
            logic = aiConsentLogic()
            logic.mount()

            logic.actions.setPendingApprovalRedirect('/replay-vision/new/template')
            expect(logic.values.pendingApprovalRedirect).toBe('/replay-vision/new/template')

            logic.unmount()
            logic = aiConsentLogic()
            logic.mount()

            expect(logic.values.pendingApprovalRedirect).toBe('/replay-vision/new/template')
        })

        it('redirects and clears the pending value once mounted with consent already accepted', () => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: false,
            })
            logic = aiConsentLogic()
            logic.mount()
            logic.actions.setPendingApprovalRedirect('/replay-vision/new/template')
            logic.unmount()

            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            logic = aiConsentLogic()
            logic.mount()

            expect(logic.values.pendingApprovalRedirect).toBe(null)
            expect(router.values.location.pathname).toContain('/replay-vision/new/template')
        })

        it('leaves navigation alone when there is nothing pending', () => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: true,
            })
            const pathnameBeforeMount = router.values.location.pathname
            logic = aiConsentLogic()
            logic.mount()

            expect(router.values.location.pathname).toBe(pathnameBeforeMount)
        })
    })

    describe('requestAiAccess', () => {
        it('marks the request sent and toasts on success', async () => {
            ;(requestAiAccessCreate as jest.Mock).mockResolvedValue({})
            initKeaTests()
            logic = aiConsentLogic()
            logic.mount()

            expect(logic.values.aiAccessRequested).toBe(false)

            await expectLogic(logic, () => {
                logic.actions.requestAiAccess()
            }).toFinishAllListeners()

            expect(requestAiAccessCreate).toHaveBeenCalledWith(MOCK_DEFAULT_ORGANIZATION.id)
            expect(logic.values.aiAccessRequested).toBe(true)
            expect(logic.values.requestingAiAccess).toBe(false)
            expect(lemonToast.success).toHaveBeenCalled()
        })

        it('surfaces an error and leaves the request unmarked when the API call fails', async () => {
            ;(requestAiAccessCreate as jest.Mock).mockRejectedValue(new Error('boom'))
            initKeaTests()
            logic = aiConsentLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.requestAiAccess()
            }).toFinishAllListeners()

            expect(logic.values.aiAccessRequested).toBe(false)
            expect(logic.values.requestingAiAccess).toBe(false)
            expect(lemonToast.error).toHaveBeenCalled()
        })
    })
})
