import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'
import { getRecentSlackChannelIds } from 'lib/integrations/slackChannel'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { InsightShortId, SubscriptionType } from '~/types'

import { subscriptionLogic } from './subscriptionLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: {
        success: jest.fn(),
        error: jest.fn(),
    },
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
                '/api/environments/:team/subscriptions': async ({ request }) => [
                    200,
                    { id: 42, ...((await request.json()) as Partial<SubscriptionType>) } as SubscriptionType,
                ],
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
                '/api/environments/:team/subscriptions': async ({ request }) => {
                    capturedBody = (await request.json()) as Partial<SubscriptionType>
                    return [200, { id: 42, ...capturedBody } as SubscriptionType]
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
                '/api/environments/:team/subscriptions': async ({ request }) => {
                    capturedBody = (await request.json()) as Partial<SubscriptionType>
                    return [200, { id: 43, ...capturedBody } as SubscriptionType]
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
})
