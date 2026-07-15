import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { OrganizationBasicType, Region, SidePanelTab, TeamPublicType } from '~/types'

import { getPublicSupportSnippet, SupportFormFields, supportLogic } from './supportLogic'
import * as SupportModal from './SupportModal'

// supportLogic and SupportModal import each other, so jest.mock('./SupportModal') leaves supportLogic
// bound to the real openSupportModal — spy on the live module export instead so the call is intercepted.
const openSupportModal = jest.spyOn(SupportModal, 'openSupportModal').mockImplementation(() => {})

describe('supportLogic', () => {
    describe('snippet helpers', () => {
        const mockedGetReplayUrl = posthog.get_session_replay_url as jest.Mock
        const organization = { id: 'org-1', name: 'Test org' } as OrganizationBasicType
        const team = { id: 42 } as TeamPublicType

        beforeEach(() => {
            mockedGetReplayUrl.mockReset()
        })

        it('rewrites the session line to the internal golink for staff triage', () => {
            mockedGetReplayUrl.mockReturnValue(`${window.location.origin}/replay/abc?t=30`)
            const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
            expect(snippet).toContain('Session: http://go/session/abc?t=30')
            expect(snippet).not.toContain(`${window.location.origin}/replay/`)
        })

        it('omits the session line when there is no recording', () => {
            mockedGetReplayUrl.mockReturnValue(undefined)
            const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
            expect(snippet).not.toContain('Session:')
        })

        it('marks the admin line as internal', () => {
            mockedGetReplayUrl.mockReturnValue(undefined)
            const snippet = getPublicSupportSnippet(Region.US, organization, team, false)
            expect(snippet).toContain('Admin (internal): http://go/adminOrg')
        })
    })

    describe('openSupportForm modal vs side panel target', () => {
        let logic: ReturnType<typeof supportLogic.build>

        beforeEach(() => {
            // sidePanelStateLogic persists its selected tab and reflects open state in the URL hash;
            // initKeaTests resets neither, so clear them to keep the gating decision deterministic.
            localStorage.clear()
            window.history.replaceState(null, '', '/')
            initKeaTests()
            sidePanelStateLogic.mount()
            logic = supportLogic.build()
            logic.mount()
            openSupportModal.mockClear()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('opens the side panel when target is sidePanel', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login', target: 'sidePanel' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(true)
            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Support)
            expect(openSupportModal).not.toHaveBeenCalled()
        })

        it('opens the modal when target is modal', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login', target: 'modal' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })

        it('falls back to sidePanelAvailable when no target is given', async () => {
            sidePanelStateLogic.actions.setSidePanelAvailable(false)
            await expectLogic(logic, () => {
                logic.actions.openSupportForm({ kind: 'support', target_area: 'login' })
            }).toFinishAllListeners()

            expect(sidePanelStateLogic.values.sidePanelOpen).toBe(false)
            expect(openSupportModal).toHaveBeenCalledTimes(1)
        })
    })

    describe('submitSupportTicket routing', () => {
        const ZENDESK_URL = 'https://posthoghelp.zendesk.com/api/v2/requests.json'
        const FORM_FIELDS: SupportFormFields = {
            name: 'Max',
            email: 'max@example.com',
            kind: 'bug',
            target_area: 'billing',
            severity_level: 'high',
            message: 'Help!',
        }

        let logic: ReturnType<typeof supportLogic.build>
        const savedFetch = global.fetch
        let fetchMock: jest.Mock

        const zendeskCalls = (): unknown[][] => fetchMock.mock.calls.filter(([url]) => url === ZENDESK_URL)

        const enableConversationsFlag = (): void => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.PRODUCT_SUPPORT_SIDE_PANEL]: true })
        }

        beforeEach(() => {
            fetchMock = jest.fn(() =>
                Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ request: { id: 123 } }),
                    text: () => Promise.resolve(''),
                } as unknown as Response)
            )
            global.fetch = fetchMock
            initKeaTests()
            logic = supportLogic.build()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
            delete (posthog as any).conversations
            global.fetch = savedFetch
        })

        it('creates a conversations ticket instead of a Zendesk one when the flag is on', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            ;(posthog as any).conversations = { isAvailable: () => true, sendMessage }
            enableConversationsFlag()

            await logic.asyncActions.submitSupportTicket(FORM_FIELDS)

            expect(sendMessage).toHaveBeenCalledTimes(1)
            expect(sendMessage).toHaveBeenCalledWith('Help!', { name: 'Max', email: 'max@example.com' }, true)
            expect(zendeskCalls()).toHaveLength(0)
            expect(logic.values.lastSubmittedTicketId).toBe('t1')
        })

        it.each([
            ['the flag is off', false, { isAvailable: () => true, sendMessage: jest.fn() }],
            [
                'sendMessage reports unavailable without sending',
                true,
                { isAvailable: () => true, sendMessage: jest.fn().mockResolvedValue(null) },
            ],
        ])('files exactly one Zendesk ticket when %s', async (_case, flagOn, conversations) => {
            ;(posthog as any).conversations = conversations
            if (flagOn) {
                enableConversationsFlag()
            }

            await expectLogic(logic, () => {
                logic.actions.submitSupportTicket(FORM_FIELDS)
            }).toFinishAllListeners()

            expect(zendeskCalls()).toHaveLength(1)
        })

        it('waits for the lazily-loaded extension before falling back to Zendesk', async () => {
            ;(posthog as any).conversations = undefined
            enableConversationsFlag()

            jest.useFakeTimers()
            try {
                const promise = (logic.asyncActions as any).submitSupportTicket(FORM_FIELDS)
                // No Zendesk request yet — the submit is still waiting for the extension
                expect(zendeskCalls()).toHaveLength(0)
                await jest.runAllTimersAsync()
                await promise
            } finally {
                jest.useRealTimers()
            }

            expect(zendeskCalls()).toHaveLength(1)
        })

        it('preserves exception context on the conversations ticket message', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            ;(posthog as any).conversations = { isAvailable: () => true, sendMessage }
            enableConversationsFlag()

            await expectLogic(logic, () => {
                logic.actions.submitSupportTicket({
                    ...FORM_FIELDS,
                    exception_event: { uuid: 'exc-1', event: '$exception' },
                })
            }).toFinishAllListeners()

            expect(sendMessage.mock.calls[0][0]).toContain('Help!')
            expect(sendMessage.mock.calls[0][0]).toContain('Exception:')
        })

        it('accepts a form submission without severity or topic when the flag is on, as those fields are hidden', async () => {
            const sendMessage = jest.fn().mockResolvedValue({ ticket_id: 't1' })
            ;(posthog as any).conversations = { isAvailable: () => true, sendMessage }
            enableConversationsFlag()

            await expectLogic(logic, () => {
                logic.actions.setSendSupportRequestValue('message', 'Just a message')
                logic.actions.submitSendSupportRequest()
            }).toFinishAllListeners()

            expect(sendMessage).toHaveBeenCalledTimes(1)
            expect(sendMessage.mock.calls[0][0]).toBe('Just a message')
        })

        it('does not fall back to Zendesk when sendMessage throws, to avoid double-filing', async () => {
            ;(posthog as any).conversations = {
                isAvailable: () => true,
                sendMessage: jest.fn().mockRejectedValue(new Error('network down')),
            }
            enableConversationsFlag()

            await logic.asyncActions.submitSupportTicket(FORM_FIELDS)

            // lastSubmittedTicketId stays null on failure — callers use this to detect the failure
            expect(zendeskCalls()).toHaveLength(0)
            expect(logic.values.lastSubmittedTicketId).toBeNull()
        })
    })
})
