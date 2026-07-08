import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import {
    RecurrenceIntervalEnumApi,
    ResourceTypeEnumApi,
    SubscriptionsDeliveriesListStatus,
    TargetTypeEnumApi,
} from '@posthog/products-subscriptions/frontend/generated/api.schemas'
import type { SubscriptionApi } from '@posthog/products-subscriptions/frontend/generated/api.schemas'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { subscriptionSceneLogic } from './subscriptionSceneLogic'

const MOCK_USER = {
    id: 1,
    uuid: '01863799-062b-0000-8a61-b2842d5f8642',
    email: 'test@posthog.com',
    first_name: 'Test',
    last_name: 'User',
    hedgehog_config: null,
} as const

const MOCK_SUBSCRIPTION: SubscriptionApi = {
    id: 1,
    resource_type: ResourceTypeEnumApi.Insight,
    insight: 101,
    dashboard: null,
    insight_short_id: 'abc123',
    resource_name: 'North star metric',
    title: 'Weekly rollup',
    dashboard_export_insights: [],
    target_type: TargetTypeEnumApi.Email,
    target_value: 'a@b.com',
    frequency: RecurrenceIntervalEnumApi.Weekly,
    interval: 1,
    start_date: '2022-01-01T00:00:00Z',
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: MOCK_USER,
    summary: 'sent every week',
    next_delivery_date: '2026-04-07T17:00:00Z',
    deleted: false,
}

const MOCK_AI_SUBSCRIPTION: SubscriptionApi = {
    id: 2,
    resource_type: ResourceTypeEnumApi.AiPrompt,
    insight: null,
    dashboard: null,
    insight_short_id: null,
    resource_name: null,
    prompt: 'Summarize weekly signups and flag any anomalies',
    title: 'Weekly AI digest',
    dashboard_export_insights: [],
    target_type: TargetTypeEnumApi.Email,
    target_value: 'a@b.com',
    frequency: RecurrenceIntervalEnumApi.Weekly,
    interval: 1,
    start_date: '2022-01-01T00:00:00Z',
    created_at: '2023-04-27T10:04:37.977401Z',
    created_by: MOCK_USER,
    summary: 'sent every week',
    next_delivery_date: '2026-04-07T17:00:00Z',
    deleted: false,
}

const MOCK_AI_SUBSCRIPTION_WITH_PLAN: SubscriptionApi = {
    ...MOCK_AI_SUBSCRIPTION,
    id: 3,
    ai_query_plan: {
        overall_intent: 'Weekly signups',
        steps: [
            { description: 'Daily signups', query_type: 'hogql', hogql: 'SELECT 1' },
            { description: 'Anomalies', query_type: 'hogql', hogql: 'SELECT 2' },
        ],
    },
}

describe('subscriptionSceneLogic', () => {
    let deliveriesRequestUrls: string[]

    beforeEach(() => {
        deliveriesRequestUrls = []
        // deliveryFeedback persists to localStorage; clear it so recorded feedback can't leak between tests.
        localStorage.clear()
    })

    it('includes status in deliveries list request when status filter is set', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/environments/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: ({ request }) => {
                    deliveriesRequestUrls.push(request.url)
                    return [200, { results: [], next: null, previous: null }]
                },
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: ({ request }) => {
                    deliveriesRequestUrls.push(request.url)
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(deliveriesRequestUrls).toHaveLength(1)
        expect(deliveriesRequestUrls[0]).not.toContain('status=')

        await expectLogic(logic, () => {
            logic.actions.setDeliveryStatusFilter(SubscriptionsDeliveriesListStatus.Failed)
        }).toFinishAllListeners()

        expect(deliveriesRequestUrls).toHaveLength(2)
        expect(deliveriesRequestUrls[1]).toContain('status=failed')
        logic.unmount()
    })

    it('loads delivery history once the subscription has loaded', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(deliveriesRequestUrls).toHaveLength(1)
        logic.unmount()
    })

    // The failure path matters too: the header button's double-submit guard would stick
    // if deliveringSubscriptionId reset only on success.
    it.each([
        { name: 'success', status: 202, terminalAction: 'deliverSubscriptionSuccess' },
        { name: 'failure', status: 500, terminalAction: 'deliverSubscriptionFailure' },
    ])('test delivery ($name) flips deliveringSubscriptionId then resets it', async ({ status, terminalAction }) => {
        let testDeliveryCalls = 0
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/`]: [200, MOCK_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/deliveries/`]: [
                    200,
                    { results: [], next: null, previous: null },
                ],
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/1/test-delivery/`]: () => {
                    testDeliveryCalls += 1
                    return [status, {}]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.deliverSubscription(1)
        }).toMatchValues({ deliveringSubscriptionId: 1 })

        await expectLogic(logic).toDispatchActions([terminalAction]).toMatchValues({
            deliveringSubscriptionId: null,
        })
        expect(testDeliveryCalls).toEqual(1)
        logic.unmount()
    })

    it('loads an AI prompt subscription and its deliveries', async () => {
        useMocks({
            get: {
                // Function form, not the `[200, body]` shorthand: useMocks serializes a bare array as
                // the whole response body, so only a function-returned tuple delivers the object itself.
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/deliveries/`]: () => {
                    deliveriesRequestUrls.push('deliveries')
                    return [200, { results: [], next: null, previous: null }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.subscription?.resource_type).toEqual(ResourceTypeEnumApi.AiPrompt)
        expect(logic.values.subscription?.prompt).toBeTruthy()
        expect(deliveriesRequestUrls).toHaveLength(1)
        logic.unmount()
    })

    it.each([
        ['positive' as const, 'email'],
        ['negative' as const, 'slack'],
    ])('captures ai_report_feedback (%s, %s) from URL params and strips them', async (feedback, source) => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            router.actions.push('/subscriptions/2', {
                feedback_delivery: 'd-123',
                feedback,
                feedback_source: source,
            })
        }).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith('ai_report_feedback', {
            subscription_id: 2,
            delivery_id: 'd-123',
            feedback,
            source,
            previous_feedback: null,
        })
        // The replace must remove the params so a refresh doesn't double-capture.
        expect(router.values.searchParams).toEqual({})
        expect(captureSpy.mock.calls.filter(([event]) => event === 'ai_report_feedback')).toHaveLength(1)

        logic.unmount()
        captureSpy.mockRestore()
    })

    it('does not re-capture from a feedback link for an already-recorded delivery', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-123', 'positive', 'in_app')
        }).toFinishAllListeners()
        captureSpy.mockClear()

        await expectLogic(logic, () => {
            router.actions.push('/subscriptions/2', {
                feedback_delivery: 'd-123',
                feedback: 'negative',
                feedback_source: 'email',
            })
        }).toFinishAllListeners()

        expect(captureSpy.mock.calls.filter(([event]) => event === 'ai_report_feedback')).toHaveLength(0)
        // Params are still stripped, and the originally recorded feedback wins.
        expect(router.values.searchParams).toEqual({})
        expect(logic.values.deliveryFeedback).toEqual({ 'd-123': 'positive' })

        logic.unmount()
        captureSpy.mockRestore()
    })

    it('persists recorded feedback across remounts', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()

        let logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-9', 'positive', 'in_app')
        }).toFinishAllListeners()
        logic.unmount()

        logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'positive' })
        // The thanks flash is transient — after a remount the row goes straight to the recorded option.
        expect(logic.values.recentlyThankedDeliveries).toEqual({})

        logic.unmount()
    })

    it('captures in-app thumbs feedback and records it per delivery', async () => {
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/2/`]: () => [200, MOCK_AI_SUBSCRIPTION],
            },
        })
        initKeaTests()
        const captureSpy = jest.spyOn(posthog, 'capture')

        const logic = subscriptionSceneLogic({ id: '2' })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-9', 'negative', 'in_app')
        }).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith('ai_report_feedback', {
            subscription_id: 2,
            delivery_id: 'd-9',
            feedback: 'negative',
            source: 'in_app',
            previous_feedback: null,
        })
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'negative' })
        // Thanks flashes first, then expiry settles the row into the recorded option.
        expect(logic.values.recentlyThankedDeliveries).toEqual({ 'd-9': true })
        await expectLogic(logic, () => {
            logic.actions.expireDeliveryThanks('d-9')
        }).toFinishAllListeners()
        expect(logic.values.recentlyThankedDeliveries).toEqual({})
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'negative' })

        // Switching the vote captures again with the previous value, and the latest one wins.
        await expectLogic(logic, () => {
            logic.actions.submitDeliveryFeedback('d-9', 'positive', 'in_app')
        }).toFinishAllListeners()
        expect(captureSpy).toHaveBeenCalledWith('ai_report_feedback', {
            subscription_id: 2,
            delivery_id: 'd-9',
            feedback: 'positive',
            source: 'in_app',
            previous_feedback: 'negative',
        })
        expect(logic.values.deliveryFeedback).toEqual({ 'd-9': 'positive' })

        logic.unmount()
        captureSpy.mockRestore()
    })

    it('runs a preview and clears it without touching delivery', async () => {
        const previewBody = {
            report: '# Weekly report',
            diagnostics: [{ description: 'Daily signups', hogql: 'SELECT 1', ok: true, error_type: null }],
        }
        let previewCalls = 0
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/`]: () => [200, MOCK_AI_SUBSCRIPTION_WITH_PLAN],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/preview/`]: () => {
                    previewCalls += 1
                    return [200, previewBody]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '3' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.previewSubscription()
        }).toFinishAllListeners()
        expect(previewCalls).toEqual(1)
        expect(logic.values.preview?.report).toEqual('# Weekly report')

        await expectLogic(logic, () => {
            logic.actions.clearPreview()
        }).toFinishAllListeners()
        expect(logic.values.preview).toBeNull()

        logic.unmount()
    })

    it('applies pending query-plan edits and saves them, resetting the editor', async () => {
        let savedBody: any = null
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/`]: () => [200, MOCK_AI_SUBSCRIPTION_WITH_PLAN],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
            },
            patch: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/`]: async (req) => {
                    savedBody = await req.request.json()
                    return [200, { ...MOCK_AI_SUBSCRIPTION_WITH_PLAN, ai_query_plan: savedBody.ai_query_plan }]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '3' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        // No edits yet → nothing to save.
        expect(logic.values.hasQueryPlanEdits).toBe(false)
        expect(logic.values.editedQueryPlan).toBeNull()

        await expectLogic(logic, () => {
            logic.actions.setQueryPlanStepHogql(1, 'SELECT 99')
        }).toFinishAllListeners()
        expect(logic.values.hasQueryPlanEdits).toBe(true)
        // Only the edited step changes; the other keeps its original HogQL.
        expect(logic.values.editedQueryPlan?.steps.map((s) => s.hogql)).toEqual(['SELECT 1', 'SELECT 99'])

        await expectLogic(logic, () => {
            logic.actions.saveQueryPlan()
        }).toFinishAllListeners()
        expect(savedBody.ai_query_plan.steps[1].hogql).toEqual('SELECT 99')
        // Save success replaces the subscription and clears the pending edits.
        expect(logic.values.queryPlanEdits).toEqual({})
        expect(logic.values.hasQueryPlanEdits).toBe(false)

        logic.unmount()
    })

    it('re-plan clears the frozen plan and reloads', async () => {
        let replanCalls = 0
        let returnPlan = true
        useMocks({
            get: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/`]: () => [
                    200,
                    returnPlan
                        ? MOCK_AI_SUBSCRIPTION_WITH_PLAN
                        : { ...MOCK_AI_SUBSCRIPTION_WITH_PLAN, ai_query_plan: null },
                ],
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/deliveries/`]: () => [
                    200,
                    { results: [], next: null, previous: null },
                ],
            },
            post: {
                [`/api/projects/${MOCK_TEAM_ID}/subscriptions/3/re-plan/`]: () => {
                    replanCalls += 1
                    returnPlan = false // the next reload sees a cleared plan
                    return [202, {}]
                },
            },
        })
        initKeaTests()

        const logic = subscriptionSceneLogic({ id: '3' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.subscription?.ai_query_plan).toBeTruthy()

        await expectLogic(logic, () => {
            logic.actions.replanSubscription()
        }).toFinishAllListeners()
        expect(replanCalls).toEqual(1)
        expect(logic.values.replanning).toBe(false)
        expect(logic.values.subscription?.ai_query_plan).toBeNull()

        logic.unmount()
    })
})
