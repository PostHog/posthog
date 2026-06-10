import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import {
    subscriptionsPreviewReportRetrieve,
    subscriptionsTestDeliveryCreate,
} from '@posthog/products-subscriptions/frontend/generated/api'

import { ApiError } from 'lib/api'
import { getRecentSlackChannelIds } from 'lib/integrations/slackChannel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, SubscriptionType } from '~/types'

import { AI_PREVIEW_TIMEOUT_MS, subscriptionLogic } from './subscriptionLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
}))

jest.mock('@posthog/products-subscriptions/frontend/generated/api', () => ({
    ...jest.requireActual('@posthog/products-subscriptions/frontend/generated/api'),
    subscriptionsTestDeliveryCreate: jest.fn(),
    subscriptionsPreviewReportRetrieve: jest.fn(),
}))

const Insight1 = '1' as InsightShortId

export const fixtureSubscriptionResponse = (id: number, args: Partial<SubscriptionType> = {}): SubscriptionType =>
    ({
        id,
        title: 'My example subscription',
        target_type: 'email',
        target_value: 'ben@posthog.com,geoff@other-company.com',
        frequency: 'monthly',
        interval: 2,
        start_date: '2022-01-01T00:09:00',
        byweekday: ['wednesday'],
        bysetpos: 1,
        ...args,
    }) as SubscriptionType

describe('subscriptionLogic', () => {
    let newLogic: ReturnType<typeof subscriptionLogic.build>
    let existingLogic: ReturnType<typeof subscriptionLogic.build>
    beforeEach(async () => {
        jest.clearAllMocks()
        window.localStorage.clear()
        useMocks({
            get: {
                '/api/environments/:team/subscriptions': { count: 1, results: [fixtureSubscriptionResponse(1)] },
                '/api/environments/:team/subscriptions/1': fixtureSubscriptionResponse(1),
                '/api/projects/:team/integrations': { count: 0, results: [] },
                '/api/environments/:team/subscriptions/summary_quota': {
                    active_count: 0,
                    limit: null,
                    at_limit: false,
                },
            },
            post: {
                '/api/environments/:team/subscriptions': (req, res, ctx) =>
                    res(ctx.json({ id: 42, ...(req.body as Partial<SubscriptionType>) } as SubscriptionType)),
            },
        })
        initKeaTests()
        newLogic = subscriptionLogic({
            insightShortId: Insight1,
            id: 'new',
        })
        existingLogic = subscriptionLogic({
            insightShortId: Insight1,
            id: 1,
        })
        newLogic.mount()
        existingLogic.mount()
    })

    afterEach(() => {
        window.localStorage.clear()
    })

    it('loads existing subscription', async () => {
        router.actions.push('/insights/123/subscriptions/1')
        await expectLogic(existingLogic).toFinishListeners().toDispatchActions(['loadSubscriptionSuccess'])
        expect(existingLogic.values.subscription).toMatchObject({
            id: 1,
            title: 'My example subscription',
            target_type: 'email',
            target_value: 'ben@posthog.com,geoff@other-company.com',
            frequency: 'monthly',
            interval: 2,
            start_date: '2022-01-01T00:09:00',
            byweekday: ['wednesday'],
            bysetpos: 1,
        })
    })

    it('updates values depending on frequency', async () => {
        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'weekly',
            bysetpos: 1,
            byweekday: ['monday'],
        })

        newLogic.actions.setSubscriptionValue('frequency', 'daily')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'daily',
            bysetpos: null,
            byweekday: null,
        })

        newLogic.actions.setSubscriptionValue('frequency', 'monthly')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            frequency: 'monthly',
            bysetpos: 1,
            byweekday: ['monday'],
        })
    })

    it('sets the type from query params', async () => {
        router.actions.push('/insights/123/subscriptions/new?target_type=slack')
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscription).toMatchObject({
            target_type: 'slack',
        })
    })

    it('does not toast when kea-forms reports client validation failure', async () => {
        await expectLogic(newLogic, () => {
            newLogic.actions.submitSubscriptionFailure(new Error('Validation Failed'), {})
        }).toFinishListeners()
        expect(lemonToast.error).not.toHaveBeenCalled()
    })

    it('toasts and maps ApiError attr to manual errors on save failure', async () => {
        const err = new ApiError('Select at least one insight', 400, undefined, {
            type: 'validation_error',
            attr: 'dashboard_export_insights',
            detail: 'Select at least one insight',
        })
        await expectLogic(newLogic, () => {
            newLogic.actions.submitSubscriptionFailure(err, {})
        }).toFinishListeners()
        expect(lemonToast.error).toHaveBeenCalledWith('Select at least one insight')
        expect(newLogic.values.subscriptionManualErrors).toEqual({
            dashboard_export_insights: 'Select at least one insight',
        })
    })

    it.each<[string, Partial<SubscriptionType>, string[]]>([
        ['a slack subscription', { target_type: 'slack', target_value: 'C123|#general', integration_id: 7 }, ['C123']],
        [
            'a non-slack target type',
            { target_type: 'email', target_value: 'ben@posthog.com', integration_id: null },
            [],
        ],
    ])('records the channel recency for %s', async (_label, subscription, expectedIds) => {
        await expectLogic(newLogic, () => {
            newLogic.actions.submitSubscriptionSuccess(subscription as SubscriptionType)
        }).toFinishListeners()

        expect(getRecentSlackChannelIds(7)).toEqual(expectedIds)
    })

    it('rejects empty prompt when resource_type is ai_prompt', async () => {
        // The parent-less /subscriptions/new route is the AI flow; its urlToAction sets
        // resource_type='ai_prompt' (the /insights/... route forces 'insight').
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({ resource_type: 'ai_prompt', prompt: '   ', title: 'AI test' })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.prompt).toBeTruthy()
    })

    it('rejects prompts exceeding 4000 characters when resource_type is ai_prompt', async () => {
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'ai_prompt',
            prompt: 'x'.repeat(4001),
            title: 'AI test',
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.prompt).toContain('4000')
    })

    it('accepts a valid AI prompt', async () => {
        router.actions.push('/insights/123/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'ai_prompt',
            prompt: 'Show me the biggest event gains last week',
            title: 'AI test',
        })
        await expectLogic(newLogic).toFinishListeners()
        expect(newLogic.values.subscriptionErrors.prompt).toBeUndefined()
    })

    it('clears a carried-over insight selection when saving an AI subscription', async () => {
        // Opening the AI flow from a dashboard pre-populates dashboard_export_insights;
        // those must not be sent, else the backend rejects insights without a dashboard.
        let capturedBody: Partial<SubscriptionType> | undefined
        useMocks({
            post: {
                '/api/environments/:team/subscriptions': (req, res, ctx) => {
                    capturedBody = req.body as Partial<SubscriptionType>
                    return res(ctx.json({ id: 42, ...capturedBody } as SubscriptionType))
                },
            },
        })
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'ai_prompt',
            prompt: 'Show me the biggest event gains last week',
            title: 'AI test',
            target_type: 'email',
            target_value: 'ben@posthog.com',
            dashboard_export_insights: [1, 2, 3],
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners().toDispatchActions(['submitSubscriptionSuccess'])
        expect(capturedBody?.dashboard_export_insights).toEqual([])
        expect(capturedBody?.dashboard).toBeUndefined()
        expect(capturedBody?.insight).toBeUndefined()
    })

    it('drops a stale prompt when saving a non-AI subscription', async () => {
        // Toggling resource_type back to insight after typing a prompt leaves it in form state;
        // it must not be sent, else the backend rejects a non-AI sub that carries a prompt.
        let capturedBody: Partial<SubscriptionType> | undefined
        useMocks({
            post: {
                '/api/environments/:team/subscriptions': (req, res, ctx) => {
                    capturedBody = req.body as Partial<SubscriptionType>
                    return res(ctx.json({ id: 43, ...capturedBody } as SubscriptionType))
                },
            },
        })
        router.actions.push('/subscriptions/new')
        await expectLogic(newLogic).toFinishListeners()
        newLogic.actions.setSubscriptionValues({
            resource_type: 'insight',
            prompt: 'stale prompt left over from the AI toggle',
            title: 'Insight test',
            target_type: 'email',
            target_value: 'ben@posthog.com',
        })
        newLogic.actions.submitSubscription()
        await expectLogic(newLogic).toFinishListeners().toDispatchActions(['submitSubscriptionSuccess'])
        expect(capturedBody?.prompt).toBeUndefined()
    })

    describe('AI preview', () => {
        const mockKickoff = subscriptionsTestDeliveryCreate as jest.Mock
        const mockPoll = subscriptionsPreviewReportRetrieve as jest.Mock

        it('does not kick off a preview for an unsaved subscription', async () => {
            newLogic.actions.generateAiPreview()
            await expectLogic(newLogic).toFinishListeners()
            expect(mockKickoff).not.toHaveBeenCalled()
            expect(newLogic.values.aiPreviewLoading).toBe(false)
        })

        it('kicks off a preview run and starts polling with the returned delivery id', async () => {
            mockKickoff.mockResolvedValue({ delivery_id: 'delivery-1' })
            existingLogic.actions.generateAiPreview()
            await expectLogic(existingLogic)
                .toDispatchActions([existingLogic.actionCreators.startAiPreviewPolling('delivery-1')])
                .toFinishListeners()
            expect(mockKickoff).toHaveBeenCalledWith(expect.any(String), 1, { preview: true })
            expect(existingLogic.values.aiPreviewLoading).toBe(true)
            expect(existingLogic.values.aiPreviewError).toBeNull()
        })

        it('surfaces a kick-off failure and stops loading', async () => {
            mockKickoff.mockRejectedValue(
                new ApiError('Delivery already in progress', 409, undefined, {
                    type: 'throttled_error',
                    detail: 'Delivery already in progress',
                })
            )
            existingLogic.actions.generateAiPreview()
            await expectLogic(existingLogic).toFinishListeners()
            expect(existingLogic.values.aiPreviewLoading).toBe(false)
            expect(existingLogic.values.aiPreviewError).toBe('Delivery already in progress')
        })

        it.each<
            [string, { status: string; ai_report: string | null; error: string | null }, string | null, string | null]
        >([
            ['completed run', { status: 'completed', ai_report: '# Report', error: null }, '# Report', null],
            [
                'failed run',
                { status: 'failed', ai_report: null, error: 'Query planning failed' },
                null,
                'Query planning failed',
            ],
            [
                'skipped run without error detail',
                { status: 'skipped', ai_report: null, error: null },
                null,
                'Preview generation did not produce a report. Please try again.',
            ],
        ])('stops polling and renders the outcome of a %s', async (_name, report, expectedMarkdown, expectedError) => {
            mockKickoff.mockResolvedValue({ delivery_id: 'delivery-1' })
            mockPoll.mockResolvedValue(report)
            existingLogic.actions.generateAiPreview()
            await expectLogic(existingLogic).toDispatchActions(['startAiPreviewPolling']).toFinishListeners()

            existingLogic.actions.loadAiPreviewReport('delivery-1')
            await expectLogic(existingLogic).toDispatchActions(['stopAiPreviewPolling']).toFinishListeners()
            expect(existingLogic.values.aiPreviewLoading).toBe(false)
            expect(existingLogic.values.aiPreviewMarkdown).toBe(expectedMarkdown)
            expect(existingLogic.values.aiPreviewError).toBe(expectedError)
        })

        it.each<[string, () => void]>([
            [
                'a still-starting run',
                () => mockPoll.mockResolvedValue({ status: 'starting', ai_report: null, error: null }),
            ],
            ['a transient poll failure', () => mockPoll.mockRejectedValue(new ApiError('Not found', 404))],
        ])('keeps polling through %s', async (_name, setupPoll) => {
            mockKickoff.mockResolvedValue({ delivery_id: 'delivery-1' })
            setupPoll()
            existingLogic.actions.generateAiPreview()
            await expectLogic(existingLogic).toDispatchActions(['startAiPreviewPolling']).toFinishListeners()

            existingLogic.actions.loadAiPreviewReport('delivery-1')
            await expectLogic(existingLogic).toFinishListeners().toNotHaveDispatchedActions(['stopAiPreviewPolling'])
            expect(existingLogic.values.aiPreviewLoading).toBe(true)
            expect(existingLogic.values.aiPreviewError).toBeNull()
        })

        it('gives up with an error once the polling window elapses', async () => {
            mockKickoff.mockResolvedValue({ delivery_id: 'delivery-1' })
            mockPoll.mockResolvedValue({ status: 'starting', ai_report: null, error: null })
            existingLogic.actions.generateAiPreview()
            await expectLogic(existingLogic).toDispatchActions(['startAiPreviewPolling']).toFinishListeners()

            existingLogic.cache.aiPreviewStartedAt = Date.now() - AI_PREVIEW_TIMEOUT_MS - 1
            existingLogic.actions.loadAiPreviewReport('delivery-1')
            await expectLogic(existingLogic).toDispatchActions(['stopAiPreviewPolling']).toFinishListeners()
            expect(existingLogic.values.aiPreviewLoading).toBe(false)
            expect(existingLogic.values.aiPreviewError).toContain('taking longer than expected')
        })
    })
})
