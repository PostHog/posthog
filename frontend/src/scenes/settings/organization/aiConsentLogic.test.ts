import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { requestAiAccessCreate } from 'products/platform_features/frontend/generated/api'

import { PendingApprovalRedirect, aiConsentLogic } from './aiConsentLogic'

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

    // Regression guards for the SSO reauthentication redirect: it unloads the page before the
    // approval request is sent, so the confirmed intent is persisted and replayed on return.
    describe('pendingApprovalRedirect', () => {
        const pendingRedirect = (overrides: Partial<PendingApprovalRedirect> = {}): PendingApprovalRedirect => ({
            url: '/replay-vision/new/template',
            organizationId: MOCK_DEFAULT_ORGANIZATION.id,
            setAt: Date.now(),
            ...overrides,
        })

        const remountWithPending = (redirect: PendingApprovalRedirect): void => {
            logic = aiConsentLogic()
            logic.mount()
            logic.actions.setPendingApprovalRedirect(redirect)
            logic.unmount()
            logic = aiConsentLogic()
            logic.mount()
        }

        it('replays the lost approval and resumes navigation on remount', async () => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: false,
            })
            remountWithPending(pendingRedirect())

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dataProcessingAccepted).toBe(true)
            expect(logic.values.pendingApprovalRedirect).toBe(null)
            expect(router.values.location.pathname).toContain('/replay-vision/new/template')
            expect(lemonToast.success).toHaveBeenCalledWith('AI data processing approved')
        })

        it('only redirects when consent was already granted before the round trip', () => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: false,
            })
            logic = aiConsentLogic()
            logic.mount()
            logic.actions.setPendingApprovalRedirect(pendingRedirect())
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

        it.each([
            { name: 'the intent is older than the TTL', overrides: { setAt: Date.now() - 16 * 60 * 1000 } },
            { name: 'the intent belongs to another organization', overrides: { organizationId: 'some-other-org' } },
        ])('drops the intent without approving when $name', async ({ overrides }) => {
            initKeaTests(true, undefined, undefined, {
                ...MOCK_DEFAULT_ORGANIZATION,
                is_ai_data_processing_approved: false,
            })
            remountWithPending(pendingRedirect(overrides))

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dataProcessingAccepted).toBe(false)
            expect(logic.values.pendingApprovalRedirect).toBe(null)
            expect(lemonToast.success).not.toHaveBeenCalled()
        })

        it('drops the intent when the sensitive session is still stale, instead of reopening the reauth modal', async () => {
            window.POSTHOG_APP_CONTEXT = {
                current_user: {
                    ...MOCK_DEFAULT_USER,
                    sensitive_session_expires_at: dayjs().subtract(1, 'minute').toISOString(),
                    organization: { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false },
                },
            } as unknown as AppContext
            initKeaTests(true)
            remountWithPending(pendingRedirect())

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.dataProcessingAccepted).toBe(false)
            expect(logic.values.pendingApprovalRedirect).toBe(null)
            expect(lemonToast.success).not.toHaveBeenCalled()
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
