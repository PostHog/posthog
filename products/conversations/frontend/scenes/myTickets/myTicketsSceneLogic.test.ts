import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sidepanelTicketsLogic } from '../../components/SidePanel/sidepanelTicketsLogic'
import { myTicketsSceneLogic } from './myTicketsSceneLogic'

describe('myTicketsSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).conversations = {
            isAvailable: () => true,
            getTickets: jest.fn().mockResolvedValue({ results: [] }),
        }
    })

    afterEach(() => {
        delete (posthog as any).conversations
    })

    // The tickets logic stays mounted for the whole session via the side panel tab icon, so its own
    // boot-time load never re-runs. Without the scene-mount refetch, navigating to /my-tickets shows
    // whatever the boot-time load returned (often nothing) until a full page reload.
    it('refetches tickets when the scene mounts while the tickets logic is already mounted', async () => {
        const ticketsLogic = sidepanelTicketsLogic.build()
        ticketsLogic.mount()
        await expectLogic(ticketsLogic).toFinishAllListeners()

        const getTickets = (posthog as any).conversations.getTickets as jest.Mock
        const callsAtBoot = getTickets.mock.calls.length
        expect(callsAtBoot).toBeGreaterThan(0)

        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()
        await expectLogic(ticketsLogic).toFinishAllListeners()

        expect(getTickets.mock.calls.length).toBe(callsAtBoot + 1)

        sceneLogic.unmount()
        ticketsLogic.unmount()
    })

    it('opens an agent draft in the support form and claims it when the person sends it', async () => {
        ;(posthog as any).conversations.sendMessage = jest
            .fn()
            .mockResolvedValue({ ticket_id: 'ticket-9', ticket_status: 'new', created_at: '2026-10-30T00:00:00Z' })
        const claimed = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team_id/posthog_support/drafts/:draft_id/': {
                    id: 'draft-1',
                    message: 'In my words:\nMy funnel is empty',
                    filing_reason: 'user_asked_for_support',
                    agent_name: 'Claude Code',
                    ticket_context: 'Drafted by an AI agent (Claude Code) through the PostHog MCP.',
                    expires_at: 0,
                    review_url: '',
                    sent: false,
                    next_step: '',
                },
            },
            post: {
                '/api/projects/:team_id/posthog_support/drafts/:draft_id/claim/': ({ params }) => {
                    claimed(params.draft_id)
                    return [204, null]
                },
            },
        })
        supportLogic.mount()
        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()

        router.actions.push(urls.myTickets(), { support_draft: 'draft-1' })
        await expectLogic(sceneLogic).toFinishAllListeners()

        expect(supportLogic.values.sendSupportRequest).toMatchObject({
            message: 'In my words:\nMy funnel is empty',
            ai_draft_id: 'draft-1',
        })
        expect(supportLogic.values.sendSupportRequest.ticket_context).toContain('Claude Code')
        expect(router.values.searchParams).not.toHaveProperty('support_draft')

        // The person may leave the scene before sending, so claiming the draft can't depend on it.
        sceneLogic.unmount()
        await supportLogic.asyncActions.submitSupportTicket({
            ...supportLogic.values.sendSupportRequest,
            email: 'person@example.com',
        })

        expect(claimed).toHaveBeenCalledWith('draft-1')
        expect((posthog as any).conversations.sendMessage).toHaveBeenCalled()
    })
})
