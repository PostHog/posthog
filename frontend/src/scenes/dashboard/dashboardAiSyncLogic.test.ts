import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    DashboardType,
    InsightColor,
    InsightLogicProps,
    InsightShortId,
    QueryBasedInsightModel,
    SubscriptionType,
} from '~/types'

import { insightAlertsLogic } from 'products/alerts/frontend/logic/insightAlertsLogic'
import type { ToolStreamEvent } from 'products/posthog_ai/frontend/types/streamTypes'
import { subscriptionsLogic } from 'products/subscriptions/frontend/components/Subscriptions/subscriptionsLogic'

import {
    DASHBOARD_AI_MUTATION_TOOLS,
    DashboardAiKnownOwnership,
    DashboardAiMutationResolution,
    DashboardAiSyncBatch,
    DashboardAiSyncCandidate,
    DashboardAiSyncTarget,
    dashboardAiSyncLogic,
    resolveDashboardAiMutation,
} from './dashboardAiSyncLogic'

let mockCommittedDashboard: DashboardType<QueryBasedInsightModel> | null = null
const mockLoadDashboard = jest.fn<Promise<void>, [unknown]>()

jest.mock('scenes/dashboard/dashboardLogic', () => ({
    ...jest.requireActual('scenes/dashboard/dashboardLogic'),
    dashboardLogic: jest.fn(() => ({
        values: {
            get dashboard(): DashboardType<QueryBasedInsightModel> | null {
                return mockCommittedDashboard
            },
        },
        asyncActions: {
            loadDashboard: (payload: unknown): Promise<void> => mockLoadDashboard(payload),
        },
    })),
}))

const dashboardId = 7
const target: DashboardAiSyncTarget = {
    dashboardId,
    tiles: [
        { tileId: 41, insightId: 101, insightShortId: 'alpha', alertIds: ['alert-1', 501] },
        { tileId: 42, insightId: 202, insightShortId: 'beta', alertIds: ['alert-2'] },
    ],
}

const emptyOwnership = (): DashboardAiKnownOwnership => ({
    subscriptionDashboardById: {},
    insightDashboardsById: {},
    alertInsightById: {},
})

function eventFor(
    toolName: string,
    innerInput: Record<string, unknown>,
    output: unknown,
    overrides: Partial<ToolStreamEvent> = {}
): ToolStreamEvent {
    return {
        streamKey: 'stream-1',
        toolCallId: 'call-1',
        toolName,
        rawToolName: 'exec',
        phase: 'completed',
        source: 'live',
        invocation: {
            toolCallId: 'call-1',
            rawServerName: 'posthog',
            rawToolName: 'exec',
            input: { command: `call --json ${toolName} ${JSON.stringify(innerInput)}` },
            output,
            status: 'completed',
            contentBlocks: [],
        },
        ...overrides,
    }
}

function resolveFor(
    toolName: string,
    innerInput: Record<string, unknown>,
    output: unknown,
    ownership: DashboardAiKnownOwnership = emptyOwnership(),
    syncTarget: DashboardAiSyncTarget = target,
    overrides: Partial<ToolStreamEvent> = {}
): DashboardAiMutationResolution {
    return resolveDashboardAiMutation(
        syncTarget,
        ownership,
        eventFor(toolName, innerInput, output, overrides),
        innerInput
    )
}

function dashboardCandidate(overrides: Partial<DashboardAiSyncCandidate> = {}): DashboardAiSyncCandidate {
    return {
        family: 'dashboard',
        dashboardId,
        tileIds: [],
        insightIds: [],
        deletesDashboard: false,
        ...overrides,
    }
}

function committedInsight(id: number, shortId: string, alertIds: string[] = []): QueryBasedInsightModel {
    return {
        id,
        short_id: shortId as InsightShortId,
        name: shortId,
        query: null,
        order: null,
        result: null,
        deleted: false,
        saved: true,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        is_sample: false,
        dashboards: [dashboardId],
        dashboard_tiles: [],
        updated_at: '2026-01-01T00:00:00Z',
        last_modified_at: '2026-01-01T00:00:00Z',
        last_modified_by: null,
        last_refresh: null,
        user_access_level: AccessControlLevel.Editor,
        alerts: alertIds.map((alertId) => ({ id: alertId })) as QueryBasedInsightModel['alerts'],
    }
}

function committedDashboard(): DashboardType<QueryBasedInsightModel> {
    return {
        id: dashboardId,
        name: 'AI dashboard',
        description: '',
        pinned: false,
        created_at: '2026-01-01T00:00:00Z',
        created_by: null,
        last_accessed_at: null,
        is_shared: false,
        deleted: false,
        creation_mode: 'default',
        user_access_level: AccessControlLevel.Editor,
        filters: {},
        tiles: [
            {
                id: 41,
                color: InsightColor.White,
                insight: committedInsight(101, 'alpha'),
            },
        ],
    }
}

function dashboardWithInsight(
    tileId: number,
    insightId: number,
    shortId: string,
    alertIds: string[] = []
): DashboardType<QueryBasedInsightModel> {
    const dashboard = committedDashboard()
    return {
        ...dashboard,
        tiles: [
            {
                id: tileId,
                color: InsightColor.White,
                insight: committedInsight(insightId, shortId, alertIds),
            },
        ],
    }
}

function insightLogicPropsForDashboard(dashboard: DashboardType<QueryBasedInsightModel>): InsightLogicProps | null {
    const insight = dashboard.tiles[0]?.insight
    return insight
        ? {
              dashboardItemId: insight.short_id,
              dashboardId: dashboard.id,
              cachedInsight: insight,
          }
        : null
}

function deferred<T>(): {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (error: unknown) => void
} {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
        resolve = resolvePromise
        reject = rejectPromise
    })
    return { promise, resolve, reject }
}

function subscription(id: number, title: string): SubscriptionType {
    return {
        id,
        title,
        target_type: 'email',
        target_value: 'demo@example.com',
        frequency: 'weekly',
    } as SubscriptionType
}

interface DashboardStructureCase {
    label: string
    toolName: string
    input: (id: unknown) => Record<string, unknown>
    output: (id: unknown) => unknown
    candidate: DashboardAiSyncCandidate
    contradictoryOutput: unknown
}

const dashboardStructureCases: DashboardStructureCase[] = [
    {
        label: 'updates dashboard metadata',
        toolName: 'dashboard-update',
        input: (id) => ({ id }),
        output: (id) => ({ id }),
        candidate: dashboardCandidate(),
        contradictoryOutput: { id: 8 },
    },
    {
        label: 'keeps the generated dashboard update alias',
        toolName: 'dashboards-update',
        input: (id) => ({ id }),
        output: (id) => ({ id }),
        candidate: dashboardCandidate(),
        contradictoryOutput: { id: 8 },
    },
    {
        label: 'creates a text tile',
        toolName: 'dashboard-create-tile',
        input: (id) => ({ id, body: '## Status' }),
        output: (id) => ({ id: '61', dashboard_id: id }),
        candidate: dashboardCandidate({ tileIds: [61] }),
        contradictoryOutput: { id: 61, dashboard_id: 8 },
    },
    {
        label: 'keeps the text tile replay alias',
        toolName: 'dashboard-create-text-tile',
        input: (id) => ({ id, body: '## Status' }),
        output: (id) => ({ id: '61', dashboard_id: id }),
        candidate: dashboardCandidate({ tileIds: [61] }),
        contradictoryOutput: { id: 61, dashboard_id: 8 },
    },
    {
        label: 'updates a text tile',
        toolName: 'dashboard-update-text-tile',
        input: (id) => ({ id, tile_id: '41', body: 'Updated' }),
        output: (id) => ({ id: '41', dashboard_id: id }),
        candidate: dashboardCandidate({ tileIds: [41] }),
        contradictoryOutput: { id: 42, dashboard_id: 7 },
    },
    {
        label: 'deletes a tile from a 204 response URL',
        toolName: 'dashboard-delete-tile',
        input: (id) => ({ id, tile_id: '41' }),
        output: (id) => ({ _posthogUrl: `https://app.example.test/project/1/dashboard/${id}` }),
        candidate: dashboardCandidate({ tileIds: [41] }),
        contradictoryOutput: { _posthogUrl: 'https://app.example.test/project/1/dashboard/8' },
    },
    {
        label: 'reorders dashboard tiles',
        toolName: 'dashboard-reorder-tiles',
        input: (id) => ({ id, tile_order: ['42', '41'] }),
        output: (id) => ({ id, tiles: [{ id: 42 }, { id: 41 }] }),
        candidate: dashboardCandidate({ tileIds: [41, 42] }),
        contradictoryOutput: { id: 8, tiles: [{ id: 42 }, { id: 41 }] },
    },
    {
        label: 'copies a tile',
        toolName: 'dashboard-tile-copy',
        input: (id) => ({ id, fromDashboardId: 6, tileId: 41 }),
        output: (id) => ({ id }),
        candidate: dashboardCandidate(),
        contradictoryOutput: { id: 8 },
    },
    {
        label: 'keeps the generated tile copy alias',
        toolName: 'dashboards-copy-tile-create',
        input: (id) => ({ id, fromDashboardId: 6, tileId: 41 }),
        output: (id) => ({ id }),
        candidate: dashboardCandidate(),
        contradictoryOutput: { id: 8 },
    },
    {
        label: 'adds dashboard widgets',
        toolName: 'dashboard-widgets-batch-add',
        input: (id) => ({ id, widgets: [{ widget_type: 'session_replay_list' }] }),
        output: (id) => ({ dashboard_id: id, tiles: [{ id: '61', dashboard_id: id }] }),
        candidate: dashboardCandidate({ tileIds: [61] }),
        contradictoryOutput: { dashboard_id: 8, tiles: [{ id: 61, dashboard_id: 7 }] },
    },
    {
        label: 'keeps the generated widget batch create alias',
        toolName: 'dashboards-widgets-batch-create',
        input: (id) => ({ id, widgets: [{ widget_type: 'session_replay_list' }] }),
        output: (id) => ({ dashboard_id: id, tiles: [{ id: '61', dashboard_id: id }] }),
        candidate: dashboardCandidate({ tileIds: [61] }),
        contradictoryOutput: { dashboard_id: 8, tiles: [{ id: 61, dashboard_id: 7 }] },
    },
    {
        label: 'updates dashboard widgets',
        toolName: 'dashboard-widgets-batch-update',
        input: (id) => ({ id, widgets: [{ tile_id: '41', name: 'Updated' }] }),
        output: (id) => ({ dashboard_id: id, tiles: [{ id: '41', dashboard_id: id }] }),
        candidate: dashboardCandidate({ tileIds: [41] }),
        contradictoryOutput: { dashboard_id: 7, tiles: [{ id: 42, dashboard_id: 7 }] },
    },
    {
        label: 'moves a tile through the create alias',
        toolName: 'dashboards-move-tile-create',
        input: (id) => ({ id, to_dashboard: 8, tile: { id: '41' } }),
        output: (id) => ({ id }),
        candidate: dashboardCandidate({ tileIds: [41] }),
        contradictoryOutput: { id: 9 },
    },
    {
        label: 'moves a tile through the partial update alias',
        toolName: 'dashboards-move-tile-partial-update',
        input: (id) => ({ id, to_dashboard: 8, tile: { id: '41' } }),
        output: (id) => ({ id }),
        candidate: dashboardCandidate({ tileIds: [41] }),
        contradictoryOutput: { id: 9 },
    },
    {
        label: 'deletes the dashboard',
        toolName: 'dashboard-delete',
        input: (id) => ({ id }),
        output: (id) => ({ id, deleted: true }),
        candidate: dashboardCandidate({ deletesDashboard: true }),
        contradictoryOutput: { id: 8, deleted: true },
    },
]

describe('resolveDashboardAiMutation candidate classification', () => {
    it('publishes the complete dashboard, insight, subscription, and alert mutation key set', () => {
        expect(DASHBOARD_AI_MUTATION_TOOLS).toEqual([
            'alert-create',
            'alert-delete',
            'alert-update',
            'dashboard-create-text-tile',
            'dashboard-create-tile',
            'dashboard-delete',
            'dashboard-delete-tile',
            'dashboard-reorder-tiles',
            'dashboard-tile-copy',
            'dashboard-update',
            'dashboard-update-text-tile',
            'dashboard-widgets-batch-add',
            'dashboard-widgets-batch-update',
            'dashboards-copy-tile-create',
            'dashboards-move-tile-create',
            'dashboards-move-tile-partial-update',
            'dashboards-update',
            'dashboards-widgets-batch-create',
            'insight-create',
            'insight-delete',
            'insight-update',
            'subscriptions-create',
            'subscriptions-delete',
            'subscriptions-partial-update',
        ])
    })

    it.each(dashboardStructureCases)(
        '$label from numeric string schema IDs',
        ({ toolName, input, output, candidate }) => {
            expect(resolveFor(toolName, input('7'), output('7')).candidate).toEqual(candidate)
        }
    )

    it.each(dashboardStructureCases)('rejects unsafe dashboard IDs for $label', ({ toolName, input, output }) => {
        expect(resolveFor(toolName, input(Number.MAX_SAFE_INTEGER + 1), output(7)).candidate).toBeNull()
    })

    it.each(dashboardStructureCases)('rejects malformed output for $label', ({ toolName, input }) => {
        expect(resolveFor(toolName, input(7), 'not a structured response').candidate).toBeNull()
    })

    it.each(dashboardStructureCases)('ignores another dashboard for $label', ({ toolName, input, output }) => {
        expect(resolveFor(toolName, input(8), output(8)).candidate).toBeNull()
    })

    it.each(dashboardStructureCases)(
        'rejects request and response disagreement for $label',
        ({ toolName, input, contradictoryOutput }) => {
            expect(resolveFor(toolName, input(7), contradictoryOutput).candidate).toBeNull()
        }
    )

    it.each(['dashboards-move-tile-create', 'dashboards-move-tile-partial-update'])(
        'recognizes the destination dashboard for %s',
        (toolName) => {
            const destinationTarget = { ...target, dashboardId: 8 }
            expect(
                resolveFor(
                    toolName,
                    { id: 7, to_dashboard: '8', tile: { id: '41' } },
                    { id: 7 },
                    emptyOwnership(),
                    destinationTarget
                ).candidate
            ).toEqual({ ...dashboardCandidate({ tileIds: [41] }), dashboardId: 8 })
        }
    )

    it('classifies a partial preserve reorder from the full dashboard response', () => {
        expect(
            resolveFor(
                'dashboard-reorder-tiles',
                { id: 7, tile_order: [42, 41], layout: 'preserve' },
                {
                    id: 7,
                    tiles: [
                        { id: 41, dashboard_id: 7 },
                        { id: 42, dashboard_id: 7 },
                        { id: 61, dashboard_id: 7 },
                    ],
                }
            ).candidate
        ).toEqual(dashboardCandidate({ tileIds: [41, 42] }))
    })

    it('classifies a complete three-column reorder when the full dashboard response contains every requested tile', () => {
        expect(
            resolveFor(
                'dashboard-reorder-tiles',
                { id: 7, tile_order: [42, 41], layout: 'three_column' },
                {
                    id: 7,
                    tiles: [
                        { id: 42, dashboard_id: 7 },
                        { id: 41, dashboard_id: 7 },
                    ],
                }
            ).candidate
        ).toEqual(dashboardCandidate({ tileIds: [41, 42] }))
    })

    it.each([
        ['a missing requested tile', [42], [{ id: 41, dashboard_id: 7 }]],
        [
            'duplicate requested tile IDs',
            [42, 42],
            [
                { id: 42, dashboard_id: 7 },
                { id: 42, dashboard_id: 7 },
            ],
        ],
        [
            'an unsafe requested tile ID',
            [Number.MAX_SAFE_INTEGER + 1],
            [{ id: Number.MAX_SAFE_INTEGER + 1, dashboard_id: 7 }],
        ],
    ])('rejects a reorder with %s', (_case, tileOrder, tiles) => {
        expect(
            resolveFor('dashboard-reorder-tiles', { id: 7, tile_order: tileOrder }, { id: 7, tiles }).candidate
        ).toBeNull()
    })

    it('rejects a direct third-party MCP event with the same dashboard tool name before changing ownership', () => {
        const ownership = emptyOwnership()
        const directInvocation = {
            ...eventFor('dashboard-update', { id: 7 }, { id: 7 }).invocation,
            rawServerName: 'third_party',
            rawToolName: 'dashboard-update',
            input: { id: 7 },
        }
        const result = resolveFor('dashboard-update', { id: 7 }, { id: 7 }, ownership, target, {
            rawToolName: 'dashboard-update',
            invocation: directInvocation,
        })

        expect(result).toEqual({ candidate: null, ownership })
        expect(result.ownership).toBe(ownership)
    })

    it('classifies an insight create from one authoritative open-dashboard tile and learns every returned membership', () => {
        const result = resolveFor(
            'insight-create',
            { dashboards: [8, '7'] },
            {
                id: 303,
                short_id: 'gamma',
                dashboard_tiles: [
                    { id: 61, dashboard_id: '7', deleted: false },
                    { id: 62, dashboard_id: 8, deleted: null },
                ],
            }
        )

        expect(result.candidate).toEqual({
            family: 'insight',
            dashboardId,
            tileIds: [61],
            insightIds: [303, 'gamma'],
            deletesDashboard: false,
        })
        expect(result.ownership.insightDashboardsById).toEqual({ 303: [7, 8], gamma: [7, 8] })
    })

    it.each(['insight-create', 'insight-update'])(
        'accepts %s without request membership when the response and identifiers are authoritative',
        (toolName) => {
            const input = toolName === 'insight-update' ? { id: 'alpha' } : { name: 'Existing query' }
            expect(
                resolveFor(toolName, input, {
                    id: 101,
                    short_id: 'alpha',
                    dashboard_tiles: [{ id: 41, dashboard_id: 7, deleted: false }],
                }).candidate
            ).toEqual({
                family: 'insight',
                dashboardId,
                tileIds: [41],
                insightIds: [101, 'alpha'],
                deletesDashboard: false,
            })
        }
    )

    it.each([
        [
            'request membership excludes the open dashboard',
            { dashboards: [8] },
            { id: 303, short_id: 'gamma', dashboard_tiles: [{ id: 61, dashboard_id: 7, deleted: false }] },
        ],
        ['request-only membership', { dashboards: [7] }, { id: 303, short_id: 'gamma' }],
        [
            'response membership excludes the open dashboard',
            { dashboards: [7] },
            { id: 303, short_id: 'gamma', dashboard_tiles: [{ id: 61, dashboard_id: 8, deleted: false }] },
        ],
        [
            'ambiguous response membership',
            { dashboards: [7] },
            {
                id: 303,
                short_id: 'gamma',
                dashboard_tiles: [
                    { id: 61, dashboard_id: 7, deleted: false },
                    { id: 62, dashboard_id: 7, deleted: false },
                ],
            },
        ],
        [
            'deleted response tile',
            { dashboards: [7] },
            { id: 303, short_id: 'gamma', dashboard_tiles: [{ id: 61, dashboard_id: 7, deleted: true }] },
        ],
        [
            'unsafe response tile ID',
            { dashboards: [7] },
            {
                id: 303,
                short_id: 'gamma',
                dashboard_tiles: [{ id: Number.MAX_SAFE_INTEGER + 1, dashboard_id: 7, deleted: false }],
            },
        ],
    ])('rejects an insight candidate with %s', (_case, input, output) => {
        expect(resolveFor('insight-create', input, output).candidate).toBeNull()
    })

    it.each([
        ['numeric ID mismatch', { id: 101 }, { id: 102, short_id: 'alpha' }],
        ['short ID mismatch', { id: 'alpha' }, { id: 101, short_id: 'beta' }],
    ])('rejects an insight update with %s', (_case, input, identifiers) => {
        expect(
            resolveFor('insight-update', input, {
                ...identifiers,
                dashboard_tiles: [{ id: 41, dashboard_id: 7, deleted: false }],
            }).candidate
        ).toBeNull()
    })

    it('deletes an insight owned by a current tile and removes both identifier forms immutably', () => {
        const ownership: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            insightDashboardsById: { 101: [7, 8], alpha: [7, 8], untouched: [8] },
        }
        const result = resolveFor(
            'insight-delete',
            { id: 'alpha' },
            { id: 101, short_id: 'alpha', deleted: true },
            ownership
        )

        expect(result.candidate).toEqual({
            family: 'insight',
            dashboardId,
            tileIds: [41],
            insightIds: [101, 'alpha'],
            deletesDashboard: false,
        })
        expect(result.ownership.insightDashboardsById).toEqual({ untouched: [8] })
        expect(ownership.insightDashboardsById).toEqual({ 101: [7, 8], alpha: [7, 8], untouched: [8] })
    })

    it('deletes an insight from learned ownership even when it is no longer in the committed tiles', () => {
        const ownership: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            insightDashboardsById: { 303: [7], gamma: [7] },
        }
        const result = resolveFor(
            'insight-delete',
            { id: 'gamma' },
            { id: 303, short_id: 'gamma', deleted: true },
            ownership,
            { dashboardId, tiles: [] }
        )

        expect(result.candidate).toEqual({
            family: 'insight',
            dashboardId,
            tileIds: [],
            insightIds: [303, 'gamma'],
            deletesDashboard: false,
        })
        expect(result.ownership.insightDashboardsById).toEqual({})
    })

    it('does not invent insight deletion ownership from a dashboards input', () => {
        expect(
            resolveFor('insight-delete', { id: 'unknown', dashboards: [7] }, { short_id: 'unknown', deleted: true })
                .candidate
        ).toBeNull()
    })

    it('rejects an insight deletion response that says the insight remains active', () => {
        expect(
            resolveFor('insight-delete', { id: 'alpha' }, { id: 101, short_id: 'alpha', deleted: false }).candidate
        ).toBeNull()
    })

    it('learns a dashboard subscription from a corroborated create response', () => {
        const result = resolveFor('subscriptions-create', { dashboard: '7' }, { id: '51', dashboard: 7 })

        expect(result.candidate).toEqual({
            family: 'subscription',
            dashboardId,
            tileIds: [],
            insightIds: [],
            deletesDashboard: false,
        })
        expect(result.ownership.subscriptionDashboardById).toEqual({ 51: 7 })
    })

    it.each(['subscriptions-create', 'subscriptions-partial-update'])(
        'rejects a %s response for another or contradictory dashboard',
        (toolName) => {
            expect(resolveFor(toolName, { id: 51, dashboard: 7 }, { id: 51, dashboard: 8 }).candidate).toBeNull()
        }
    )

    it('classifies a subscription update from its validated full response', () => {
        expect(
            resolveFor('subscriptions-partial-update', { id: 51 }, { id: 51, dashboard: 7 }).candidate
        ).toMatchObject({
            family: 'subscription',
            dashboardId,
        })
    })

    it('uses learned subscription ownership for an ID-only update and 204 delete, then removes it', () => {
        const learned: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            subscriptionDashboardById: { 51: 7 },
        }
        const updated = resolveFor('subscriptions-partial-update', { id: '51' }, { id: '51' }, learned)
        expect(updated.candidate).toMatchObject({ family: 'subscription', dashboardId })
        expect(updated.ownership.subscriptionDashboardById).toEqual({ 51: 7 })

        const deleted = resolveFor(
            'subscriptions-delete',
            { id: '51' },
            { _posthogUrl: '/subscriptions' },
            updated.ownership
        )
        expect(deleted.candidate).toMatchObject({ family: 'subscription', dashboardId })
        expect(deleted.ownership.subscriptionDashboardById).toEqual({})
        expect(learned.subscriptionDashboardById).toEqual({ 51: 7 })
    })

    it('rejects learned subscription ownership for another dashboard and unsafe IDs', () => {
        const ownership: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            subscriptionDashboardById: { 51: 8 },
        }
        expect(resolveFor('subscriptions-delete', { id: 51 }, { id: 51 }, ownership).candidate).toBeNull()
        expect(
            resolveFor('subscriptions-delete', { id: Number.MAX_SAFE_INTEGER + 1 }, { id: 51 }, ownership).candidate
        ).toBeNull()
    })

    it('rejects a subscription deletion response that says the subscription remains active', () => {
        const ownership: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            subscriptionDashboardById: { 51: 7 },
        }
        expect(
            resolveFor('subscriptions-delete', { id: 51 }, { id: 51, deleted: false }, ownership).candidate
        ).toBeNull()
    })

    it('learns an alert on an insight in the open dashboard', () => {
        const result = resolveFor(
            'alert-create',
            { insight: '101' },
            { id: 'alert-new', insight: 101, insight_short_id: 'alpha' }
        )

        expect(result.candidate).toEqual({
            family: 'alert',
            dashboardId,
            tileIds: [41],
            insightIds: [101, 'alpha'],
            deletesDashboard: false,
        })
        expect(result.ownership.alertInsightById).toEqual({ 'alert-new': '101' })
    })

    it('classifies an alert update from a validated response without prior ownership', () => {
        expect(
            resolveFor('alert-update', { id: 'alert-new' }, { id: 'alert-new', insight: 202, insight_short_id: 'beta' })
                .candidate
        ).toEqual({
            family: 'alert',
            dashboardId,
            tileIds: [42],
            insightIds: [202, 'beta'],
            deletesDashboard: false,
        })
    })

    it('uses learned alert ownership for an ID-only update', () => {
        const ownership: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            alertInsightById: { 'alert-new': '101' },
        }
        expect(resolveFor('alert-update', { id: 'alert-new' }, { id: 'alert-new' }, ownership).candidate).toEqual({
            family: 'alert',
            dashboardId,
            tileIds: [41],
            insightIds: [101, 'alpha'],
            deletesDashboard: false,
        })
    })

    it('resolves a cold ID-only alert delete from committed tile alert IDs and removes that ownership', () => {
        const result = resolveFor('alert-delete', { id: 'alert-1' }, {})

        expect(result.candidate).toEqual({
            family: 'alert',
            dashboardId,
            tileIds: [41],
            insightIds: [101, 'alpha'],
            deletesDashboard: false,
        })
        expect(result.ownership.alertInsightById).toEqual({ 501: '101' })
    })

    it.each(['{}', '  { }\n'])('accepts an empty JSON object string from call --json alert-delete: %p', (output) => {
        const result = resolveFor('alert-delete', { id: 'alert-1' }, output)

        expect(result.candidate).toEqual({
            family: 'alert',
            dashboardId,
            tileIds: [41],
            insightIds: [101, 'alpha'],
            deletesDashboard: false,
        })
        expect(result.ownership.alertInsightById).toEqual({ 501: '101' })
    })

    it.each([
        ['an array', []],
        ['a non-empty malformed object', { unexpected: true }],
    ])('rejects alert deletion output shaped as %s', (_case, output) => {
        const ownership = emptyOwnership()
        const result = resolveFor('alert-delete', { id: 'alert-1' }, output, ownership)

        expect(result).toEqual({ candidate: null, ownership })
        expect(result.ownership).toBe(ownership)
    })

    it('rejects malformed alert deletion output instead of treating it as an empty 204 response', () => {
        const ownership = emptyOwnership()
        const result = resolveFor('alert-delete', { id: 'alert-1' }, 'not a structured response', ownership)

        expect(result).toEqual({ candidate: null, ownership })
        expect(result.ownership).toBe(ownership)
    })

    it.each([
        ['a JSON array', '[]'],
        ['a non-empty JSON object', '{"id":"alert-1"}'],
        ['JSON null', 'null'],
        ['a JSON scalar', '7'],
        ['malformed JSON', '{'],
        ['TOON-like non-empty content', 'id: alert-1'],
    ])('rejects alert deletion string output shaped as %s', (_case, output) => {
        const ownership = emptyOwnership()
        const result = resolveFor('alert-delete', { id: 'alert-1' }, output, ownership)

        expect(result).toEqual({ candidate: null, ownership })
        expect(result.ownership).toBe(ownership)
    })

    it('rejects an alert deletion response that says the alert remains active', () => {
        expect(resolveFor('alert-delete', { id: 'alert-1' }, { id: 'alert-1', deleted: false }).candidate).toBeNull()
    })

    it('rejects a dashboard deletion response that says the dashboard remains active', () => {
        expect(resolveFor('dashboard-delete', { id: 7 }, { id: 7, deleted: false }).candidate).toBeNull()
    })

    it.each([
        ['an insight outside this dashboard', { id: 'alert-new', insight: 999 }],
        ['a mismatched numeric insight ID', { id: 'alert-new', insight: 202, insight_short_id: 'alpha' }],
        ['a mismatched insight short ID', { id: 'alert-new', insight: 101, insight_short_id: 'beta' }],
    ])('rejects an alert candidate with %s', (_case, output) => {
        expect(resolveFor('alert-create', { insight: 101 }, output).candidate).toBeNull()
    })

    it('rejects an alert response that contradicts learned ownership', () => {
        const ownership: DashboardAiKnownOwnership = {
            ...emptyOwnership(),
            alertInsightById: { 'alert-new': '101' },
        }
        const result = resolveFor(
            'alert-update',
            { id: 'alert-new' },
            { id: 'alert-new', insight: 202, insight_short_id: 'beta' },
            ownership
        )

        expect(result).toEqual({ candidate: null, ownership })
    })

    it('fails closed for incomplete, failed, unknown, or unparseable mutations without changing ownership', () => {
        const ownership = emptyOwnership()
        const cases: Array<[string, ToolStreamEvent, Record<string, unknown> | null]> = [
            ['missing input', eventFor('dashboard-update', { id: 7 }, { id: 7 }), null],
            ['failed event', eventFor('dashboard-update', { id: 7 }, { id: 7 }, { phase: 'failed' }), { id: 7 }],
            [
                'incomplete invocation',
                {
                    ...eventFor('dashboard-update', { id: 7 }, { id: 7 }),
                    invocation: { ...eventFor('dashboard-update', { id: 7 }, { id: 7 }).invocation, status: 'failed' },
                },
                { id: 7 },
            ],
            ['unknown tool', eventFor('dashboard-get', { id: 7 }, { id: 7 }), { id: 7 }],
            ['unparseable output', eventFor('dashboard-update', { id: 7 }, ''), { id: 7 }],
        ]

        for (const [_case, event, input] of cases) {
            const result = resolveDashboardAiMutation(target, ownership, event, input)
            expect(result).toEqual({ candidate: null, ownership })
            expect(result.ownership).toBe(ownership)
        }
    })

    describe('dashboard synchronization', () => {
        it('stores immutable sorted and deduplicated synchronization batches', () => {
            initKeaTests()
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()
            const batch: DashboardAiSyncBatch = {
                families: ['insight', 'dashboard', 'insight'],
                tileIds: [9, 3, 9],
                insightIds: ['zeta', 2, 'alpha', 2],
                queuedEventCount: 3,
                startedAt: 123,
            }

            logic.actions.setActiveBatch(batch)

            expect(logic.values.activeBatch).toEqual({
                families: ['dashboard', 'insight'],
                tileIds: [3, 9],
                insightIds: [2, 'alpha', 'zeta'],
                queuedEventCount: 3,
                startedAt: 123,
            })
            batch.tileIds.push(1)
            batch.insightIds.push('mutated')
            expect(logic.values.activeBatch?.tileIds).toEqual([3, 9])
            expect(logic.values.activeBatch?.insightIds).toEqual([2, 'alpha', 'zeta'])

            const ownership: DashboardAiKnownOwnership = {
                subscriptionDashboardById: { 71: dashboardId },
                insightDashboardsById: { 101: [dashboardId] },
                alertInsightById: { 501: '101' },
            }
            logic.actions.setKnownOwnership(ownership)
            ownership.subscriptionDashboardById[71] = 8
            ownership.insightDashboardsById[101]!.push(8)
            ownership.alertInsightById[501] = '202'
            expect(logic.values.knownOwnership).toEqual({
                subscriptionDashboardById: { 71: dashboardId },
                insightDashboardsById: { 101: [dashboardId] },
                alertInsightById: { 501: '101' },
            })
            logic.unmount()
        })

        it('serializes structural reloads into one active and one merged successor batch', async () => {
            initKeaTests()
            mockCommittedDashboard = committedDashboard()
            const firstReload = deferred<void>()
            const secondReload = deferred<void>()
            mockLoadDashboard
                .mockReset()
                .mockReturnValueOnce(firstReload.promise)
                .mockReturnValueOnce(secondReload.promise)

            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()

            logic.actions.applyToolCompletion(
                eventFor('dashboard-create-tile', { id: 7 }, { id: 63, dashboard_id: 7 }),
                { id: 7 }
            )
            logic.actions.applyToolCompletion(
                eventFor('dashboard-update-text-tile', { id: 7, tile_id: 42 }, { id: 42, dashboard_id: 7 }),
                { id: 7, tile_id: 42 }
            )
            logic.actions.applyToolCompletion(
                eventFor(
                    'dashboard-reorder-tiles',
                    { id: 7, tile_order: [42, 41] },
                    { id: 7, tiles: [{ id: 42 }, { id: 41 }] }
                ),
                { id: 7, tile_order: [42, 41] }
            )

            expect(mockLoadDashboard).toHaveBeenCalledTimes(1)
            expect(logic.values.activeBatch).toMatchObject({
                families: ['dashboard'],
                tileIds: [63],
                insightIds: [],
                queuedEventCount: 1,
                startedAt: expect.any(Number),
            })
            expect(logic.values.queuedBatch).toMatchObject({
                families: ['dashboard'],
                tileIds: [41, 42],
                insightIds: [],
                queuedEventCount: 2,
                startedAt: expect.any(Number),
            })

            firstReload.resolve()
            await waitFor(() => expect(mockLoadDashboard).toHaveBeenCalledTimes(2))

            secondReload.resolve()
            await waitFor(() => expect(logic.values.activeBatch).toBeNull())
            logic.unmount()
        })

        it('refreshes a mounted subscription list through a create, ID-only update, and 204 delete chain', async () => {
            initKeaTests()
            mockCommittedDashboard = committedDashboard()
            mockLoadDashboard.mockReset()

            const initialResponse = { results: [], count: 0 }
            const listSpy = jest.spyOn(api.subscriptions, 'list').mockResolvedValue(initialResponse)
            const mountedSubscriptions = subscriptionsLogic({ dashboardId })
            mountedSubscriptions.mount()
            await waitFor(() => expect(mountedSubscriptions.values.subscriptionsLoading).toBe(false))

            const created = deferred<{ results: SubscriptionType[]; count: number }>()
            const updated = deferred<{ results: SubscriptionType[]; count: number }>()
            const deleted = deferred<{ results: SubscriptionType[]; count: number }>()
            const directResponses = [created, updated, deleted]
            let directRequestIndex = 0
            listSpy.mockReset().mockImplementation(({ dashboardId: requestedDashboardId, dashboardTiles }) => {
                if (dashboardTiles) {
                    return Promise.resolve(initialResponse)
                }
                expect(requestedDashboardId).toBe(dashboardId)
                return directResponses[directRequestIndex++]!.promise
            })

            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()
            logic.actions.applyToolCompletion(
                eventFor('subscriptions-create', { dashboard: 7 }, { id: 71, dashboard: 7 }),
                { dashboard: 7 }
            )
            await waitFor(() => expect(directRequestIndex).toBe(1))
            logic.actions.applyToolCompletion(eventFor('subscriptions-partial-update', { id: 71 }, { id: 71 }), {
                id: 71,
            })
            await waitFor(() => expect(directRequestIndex).toBe(2))
            logic.actions.applyToolCompletion(
                eventFor('subscriptions-delete', { id: 71 }, { _posthogUrl: '/subscriptions' }),
                { id: 71 }
            )

            await waitFor(() => expect(directRequestIndex).toBe(3))
            expect(logic.values.knownOwnership.subscriptionDashboardById).toEqual({})

            deleted.resolve({ results: [], count: 0 })
            await waitFor(() => expect(mountedSubscriptions.values.subscriptionsLoading).toBe(false))
            updated.resolve({ results: [subscription(71, 'Updated')], count: 1 })
            created.resolve({ results: [subscription(71, 'Created')], count: 1 })
            await waitFor(() => expect(mountedSubscriptions.values.subscriptions).toEqual([]))

            logic.actions.applyToolCompletion(
                eventFor('subscriptions-create', { dashboard: 8 }, { id: 72, dashboard: 8 }),
                { dashboard: 8 }
            )
            expect(directRequestIndex).toBe(3)
            expect(mockLoadDashboard).not.toHaveBeenCalled()

            logic.unmount()
            mountedSubscriptions.unmount()
            listSpy.mockRestore()
        })

        it('reloads an authoritative insight create and highlights its exact committed tile', async () => {
            initKeaTests()
            mockCommittedDashboard = committedDashboard()
            const reload = deferred<void>()
            mockLoadDashboard.mockReset().mockReturnValue(reload.promise)
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()

            logic.actions.applyToolCompletion(
                eventFor(
                    'insight-create',
                    { dashboards: [7] },
                    {
                        id: 303,
                        short_id: 'gamma',
                        dashboard_tiles: [{ id: 61, dashboard_id: 7, deleted: false }],
                    }
                ),
                { dashboards: [7] }
            )
            expect(mockLoadDashboard).toHaveBeenCalledTimes(1)

            mockCommittedDashboard = dashboardWithInsight(61, 303, 'gamma')
            reload.resolve()
            await waitFor(() => expect(logic.values.activeBatch).toBeNull())
            expect(logic.values.transientHighlightedTileIds).toEqual([61])

            logic.actions.applyToolCompletion(
                eventFor('insight-create', { dashboards: [7] }, { id: 404, short_id: 'request-only' }),
                { dashboards: [7] }
            )
            expect(mockLoadDashboard).toHaveBeenCalledTimes(1)
            logic.unmount()
        })

        it('refreshes only the mounted alert logic for the exact dashboard insight', async () => {
            initKeaTests()
            mockCommittedDashboard = dashboardWithInsight(41, 101, 'alpha')
            mockLoadDashboard.mockReset()
            const alertListSpy = jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [], count: 0 })
            const insightLogicProps = insightLogicPropsForDashboard(mockCommittedDashboard)!
            const mountedAlerts = insightAlertsLogic({
                insightId: 101,
                insightLogicProps,
                deferInitialAlertsLoad: true,
            })
            mountedAlerts.mount()
            alertListSpy.mockClear()
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()

            logic.actions.applyToolCompletion(
                eventFor(
                    'alert-create',
                    { insight: 101 },
                    { id: 'alert-new', insight: 101, insight_short_id: 'alpha' }
                ),
                { insight: 101 }
            )
            await waitFor(() => expect(alertListSpy).toHaveBeenCalledWith(101))

            logic.actions.applyToolCompletion(
                eventFor('alert-create', { insight: 999 }, { id: 'other', insight: 999, insight_short_id: 'other' }),
                { insight: 999 }
            )
            expect(alertListSpy).toHaveBeenCalledTimes(1)
            expect(mockLoadDashboard).not.toHaveBeenCalled()

            logic.unmount()
            mountedAlerts.unmount()
            alertListSpy.mockRestore()
        })

        it('refreshes a cold ID-only alert delete from committed tile alert ownership', async () => {
            initKeaTests()
            mockCommittedDashboard = dashboardWithInsight(41, 101, 'alpha', ['alert-cold'])
            mockLoadDashboard.mockReset()
            const alertListSpy = jest.spyOn(api.alerts, 'list').mockResolvedValue({ results: [], count: 0 })
            const insightLogicProps = insightLogicPropsForDashboard(mockCommittedDashboard)!
            const mountedAlerts = insightAlertsLogic({
                insightId: 101,
                insightLogicProps,
                deferInitialAlertsLoad: true,
            })
            mountedAlerts.mount()
            alertListSpy.mockClear()
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()

            logic.actions.applyToolCompletion(eventFor('alert-delete', { id: 'alert-cold' }, ''), {
                id: 'alert-cold',
            })

            await waitFor(() => expect(alertListSpy).toHaveBeenCalledWith(101))
            expect(logic.values.knownOwnership.alertInsightById).toEqual({})

            logic.unmount()
            mountedAlerts.unmount()
            alertListSpy.mockRestore()
        })

        it('routes an open-dashboard deletion to the dashboard list without reloading', () => {
            initKeaTests()
            router.actions.push(urls.dashboard(dashboardId))
            mockCommittedDashboard = committedDashboard()
            mockLoadDashboard.mockReset()
            const routerPushSpy = jest.spyOn(router.actions, 'push')
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()

            logic.actions.applyToolCompletion(
                eventFor('dashboard-delete', { id: dashboardId }, { id: dashboardId, deleted: true }),
                { id: dashboardId }
            )

            expect(routerPushSpy).toHaveBeenCalledWith(urls.dashboards())
            expect(mockLoadDashboard).not.toHaveBeenCalled()
            logic.unmount()
            routerPushSpy.mockRestore()
        })

        it('continues with a queued successor after the active dashboard reload fails', async () => {
            initKeaTests()
            const committed = committedDashboard()
            mockCommittedDashboard = committed
            const firstReload = deferred<void>()
            const successorReload = deferred<void>()
            mockLoadDashboard
                .mockReset()
                .mockReturnValueOnce(firstReload.promise)
                .mockReturnValueOnce(successorReload.promise)
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()

            logic.actions.applyToolCompletion(eventFor('dashboard-update', { id: 7 }, { id: 7 }), { id: 7 })
            logic.actions.applyToolCompletion(
                eventFor('dashboard-update-text-tile', { id: 7, tile_id: 41 }, { id: 41, dashboard_id: 7 }),
                { id: 7, tile_id: 41 }
            )
            firstReload.reject(new Error('reload failed'))

            await waitFor(() => expect(mockLoadDashboard).toHaveBeenCalledTimes(2))
            expect(mockCommittedDashboard).toBe(committed)
            expect(logic.values.activeBatch?.tileIds).toEqual([41])
            successorReload.resolve()
            await waitFor(() => expect(logic.values.activeBatch).toBeNull())
            expect(logic.values.queuedBatch).toBeNull()
            logic.unmount()
        })

        it('ignores a direct third-party same-name event without any side effect', () => {
            initKeaTests()
            router.actions.push(urls.dashboard(dashboardId))
            const startingPath = router.values.location.pathname
            mockCommittedDashboard = committedDashboard()
            mockLoadDashboard.mockReset()
            jest.mocked(posthog.capture).mockClear()
            const subscriptionFindMountedSpy = jest.spyOn(subscriptionsLogic, 'findMounted')
            const alertFindMountedSpy = jest.spyOn(insightAlertsLogic, 'findMounted')
            const logic = dashboardAiSyncLogic({ dashboardId })
            logic.mount()
            const directInvocation = {
                ...eventFor('dashboard-update', { id: 7 }, { id: 7 }).invocation,
                rawServerName: 'third_party',
                rawToolName: 'dashboard-update',
                input: { id: 7 },
            }

            logic.actions.applyToolCompletion(
                eventFor(
                    'dashboard-update',
                    { id: 7 },
                    { id: 7 },
                    {
                        rawToolName: 'dashboard-update',
                        invocation: directInvocation,
                    }
                ),
                { id: 7 }
            )

            expect(mockLoadDashboard).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toBe(startingPath)
            expect(logic.values.transientHighlightedTileIds).toEqual([])
            expect(logic.values.knownOwnership).toEqual(emptyOwnership())
            expect(subscriptionFindMountedSpy).not.toHaveBeenCalled()
            expect(alertFindMountedSpy).not.toHaveBeenCalled()
            expect(posthog.capture).not.toHaveBeenCalled()
            logic.unmount()
            subscriptionFindMountedSpy.mockRestore()
            alertFindMountedSpy.mockRestore()
        })
    })
})
