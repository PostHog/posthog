import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'lib/logic/billing/billingLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingType } from '~/types'

import { liveTicketsLogic, sidepanelTicketsLogic } from '../../components/SidePanel/sidepanelTicketsLogic'
import { myTicketsSceneLogic } from './myTicketsSceneLogic'

jest.mock('../../components/SidePanel/ticketsAcrossTabs', () => ({
    loadTicketsAcrossTabs: jest.fn((fetchTickets) => fetchTickets()),
    clearSharedTickets: jest.fn(),
}))

describe('myTicketsSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
        ;(posthog as any).conversations = {
            isAvailable: () => true,
            getTickets: jest.fn().mockResolvedValue({ results: [] }),
        }
    })

    afterEach(() => {
        jest.useRealTimers()
        jest.restoreAllMocks()
        delete (posthog as any).conversations
    })

    it.each([
        [false, 'old first'],
        [true, 'old first'],
        [false, 'new first'],
        [true, 'new first'],
        [false, 'old rejection'],
        [true, 'old rejection'],
    ])('keeps requests scoped to their mount with reused logic=%s and %s', async (reuseLogic, completion) => {
        jest.useFakeTimers()
        jest.spyOn(console, 'error').mockImplementation(() => {})
        const toastError = jest.spyOn(lemonToast, 'error')
        const getTickets = (posthog as any).conversations.getTickets as jest.Mock
        const oldResponse = {
            results: [{ id: 'old-ticket', status: 'open', message_count: 1, created_at: '2026-07-21T00:00:00Z' }],
        }
        const newResponse = { results: [{ ...oldResponse.results[0], id: 'new-ticket' }] }
        let finishOld!: (response: typeof oldResponse) => void
        let rejectOld!: (error: Error) => void
        let finishNew!: (response: typeof newResponse) => void
        getTickets
            .mockReturnValueOnce(
                new Promise<typeof oldResponse>((resolve, reject) => {
                    finishOld = resolve
                    rejectOld = reject
                })
            )
            .mockReturnValueOnce(
                new Promise<typeof newResponse>((resolve) => {
                    finishNew = resolve
                })
            )
        const oldTicketsLogic = sidepanelTicketsLogic.build()
        oldTicketsLogic.mount()
        const unmountOldSupport = liveTicketsLogic.mount()
        unmountOldSupport()
        oldTicketsLogic.unmount()

        const newTicketsLogic = reuseLogic ? oldTicketsLogic : sidepanelTicketsLogic.build()
        newTicketsLogic.mount()
        const unmountNewSupport = liveTicketsLogic.mount()
        if (completion === 'new first') {
            finishNew(newResponse)
            await jest.advanceTimersByTimeAsync(0)
        }
        if (completion === 'old rejection') {
            rejectOld(new Error('old request failed'))
        } else {
            finishOld(oldResponse)
        }
        await jest.advanceTimersByTimeAsync(0)
        expect(newTicketsLogic.values.tickets).toEqual(completion === 'new first' ? newResponse.results : [])
        expect(newTicketsLogic.values.ticketsRequestsInFlight).toBe(completion === 'new first' ? 0 : 1)
        expect(newTicketsLogic.values.ticketsLoading).toBe(completion !== 'new first')
        expect(toastError).not.toHaveBeenCalled()
        getTickets.mockClear()
        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(getTickets).toHaveBeenCalledTimes(completion === 'new first' ? 1 : 0)

        finishNew(newResponse)
        await jest.advanceTimersByTimeAsync(0)
        sceneLogic.unmount()
        unmountNewSupport()
        newTicketsLogic.unmount()
    })

    it('does not add a scene request while a second forced request is still pending', async () => {
        jest.useFakeTimers()
        const ticketsLogic = sidepanelTicketsLogic.build()
        ticketsLogic.mount()
        const unmountSupport = liveTicketsLogic.mount()
        await jest.advanceTimersByTimeAsync(0)
        const getTickets = (posthog as any).conversations.getTickets as jest.Mock
        let finishFirst!: () => void
        let finishSecond!: () => void
        getTickets
            .mockReturnValueOnce(
                new Promise<void>((resolve) => {
                    finishFirst = resolve
                })
            )
            .mockReturnValueOnce(
                new Promise<void>((resolve) => {
                    finishSecond = resolve
                })
            )
        ticketsLogic.actions.loadTickets(true)
        ticketsLogic.actions.loadTickets(true)

        finishFirst()
        await jest.advanceTimersByTimeAsync(0)
        getTickets.mockClear()
        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(getTickets).not.toHaveBeenCalled()

        finishSecond()
        await jest.advanceTimersByTimeAsync(0)
        sceneLogic.unmount()
        unmountSupport()
        ticketsLogic.unmount()
    })

    it.each([
        ['cold mount', false, false],
        ['retry after a panel failure', true, false],
        ['return after an earlier successful load', false, true],
    ])('loads tickets once on %s', async (_case, supportOpen, primed) => {
        const ticketsLogic = sidepanelTicketsLogic.build()
        ticketsLogic.mount()
        const getTickets = (posthog as any).conversations.getTickets as jest.Mock
        let unmountSupport: (() => void) | undefined
        if (primed) {
            const unmountPrevious = liveTicketsLogic.mount()
            await expectLogic(ticketsLogic).toFinishAllListeners()
            unmountPrevious()
            getTickets.mockClear()
        }
        if (supportOpen) {
            jest.spyOn(console, 'error').mockImplementation(() => {})
            getTickets.mockRejectedValueOnce(new Error('unavailable'))
            unmountSupport = liveTicketsLogic.mount()
            await expectLogic(ticketsLogic).toFinishAllListeners()
            getTickets.mockClear()
        }

        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()
        await expectLogic(ticketsLogic).toFinishAllListeners()

        expect(getTickets).toHaveBeenCalledTimes(1)
        expect(liveTicketsLogic.isMounted()).toBe(true)
        sceneLogic.unmount()
        unmountSupport?.()
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
                    message: 'Request: My funnel is empty',
                    ticket_context: 'Drafted by an AI agent through the PostHog MCP.',
                    expires_at: 0,
                    review_url: '',
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
            message: 'Request: My funnel is empty',
            ticket_context: 'Drafted by an AI agent through the PostHog MCP.',
            ai_draft_id: 'draft-1',
        })
        expect(router.values.searchParams).not.toHaveProperty('support_draft')
        expect(sceneLogic.values.isReviewingDraft).toBe(true)

        sceneLogic.unmount()
        await supportLogic.asyncActions.submitSupportTicket({
            ...supportLogic.values.sendSupportRequest,
            email: 'person@example.com',
        })

        expect(claimed).toHaveBeenCalledWith('draft-1')
        expect((posthog as any).conversations.sendMessage).toHaveBeenCalled()
    })

    it('keeps the draft link when the draft fails to load for a reason other than a missing draft', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/posthog_support/drafts/:draft_id/': () => [503, { detail: 'Unavailable' }],
            },
        })
        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()

        router.actions.push(urls.myTickets(), { support_draft: 'draft-1' })
        await expectLogic(sceneLogic).toFinishAllListeners()

        expect(router.values.searchParams).toHaveProperty('support_draft', 'draft-1')
        expect(sceneLogic.values.isReviewingDraft).toBe(false)

        sceneLogic.unmount()
    })

    it.each([
        ['free', 'not_entitled'],
        ['paid', 'ready'],
    ] as const)('offers to send an agent draft on the %s plan only when tickets are allowed', (plan, state) => {
        billingLogic.mount()
        const sceneLogic = myTicketsSceneLogic.build()
        sceneLogic.mount()

        expect(sceneLogic.values.draftReviewState).toBe('checking_plan')
        billingLogic.actions.loadBillingSuccess({ subscription_level: plan } as BillingType)
        expect(sceneLogic.values.draftReviewState).toBe(state)

        sceneLogic.unmount()
    })
})
