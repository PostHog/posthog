import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import type { ApplyOp, SetupPlanResponse, Suggestion } from './setupPlanLogic'
import { setupPlanLogic } from './setupPlanLogic'

const suggestion = (overrides: Partial<Suggestion> = {}): Suggestion => ({
    id: 'add_source_mapping:meta_ads:fb-ads',
    kind: 'add_source_mapping',
    source: 'deterministic',
    severity: 'warning',
    confidence: 0.8,
    title: "Map utm_source 'fb-ads' to Meta Ads",
    evidence: '500 events arrive tagged fb-ads.',
    unlocks: ['attribution'],
    apply: { op: 'add_custom_source_mapping', integration: 'MetaAds', raw_utm_source: 'fb-ads' },
    also_recommended: [],
    safe_to_batch: true,
    rank_score: 10,
    integration: 'MetaAds',
    deep_link: null,
    docs_url: null,
    spend_at_risk: 0,
    event_volume: 500,
    ...overrides,
})

const plan = (suggestions: Suggestion[]): SetupPlanResponse => ({
    suggestions,
    readiness: [],
    degraded: [],
    truncated: false,
    summary: `${suggestions.length} suggestion(s)`,
})

const UNDO_OPS: ApplyOp[] = [{ op: 'remove_custom_source_mapping', integration: 'MetaAds', raw_utm_source: 'fb-ads' }]

describe('setupPlanLogic', () => {
    let logic: ReturnType<typeof setupPlanLogic.build>
    let applyRequests: any[]

    beforeEach(() => {
        applyRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': () => [200, plan([suggestion()])],
                '/api/environments/:team_id/marketing_analytics/utm_audit': () => [200, {}],
            },
            post: {
                '/api/projects/:team_id/marketing_analytics/apply_setup_ops': async ({ request }) => {
                    applyRequests.push(await request.json())
                    return [200, { applied: [], undo_ops: UNDO_OPS }]
                },
            },
        })
        initKeaTests()
        logic = setupPlanLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads the plan', async () => {
        await expectLogic(logic, () => logic.actions.loadSetupPlan())
            .toFinishAllListeners()
            .toMatchValues({ suggestions: [expect.objectContaining({ id: suggestion().id })] })
    })

    it('sends the apply payload verbatim', async () => {
        await expectLogic(logic, () => logic.actions.applySuggestion(suggestion())).toFinishAllListeners()

        expect(applyRequests[0].ops).toEqual([suggestion().apply])
    })

    it('collapses the row optimistically once the op succeeds', async () => {
        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        expect(logic.values.visibleSuggestions).toHaveLength(1)

        await expectLogic(logic, () => logic.actions.applySuggestion(suggestion())).toDispatchActions(['markApplied'])
    })

    it('marks only the rows the request owns, not whatever is applying', async () => {
        // An undo starts no rows of its own. Reading the global applying set meant it
        // adopted a concurrent apply's ids and collapsed those rows when it landed.
        // Asserting on the action payload rather than the reducer: the reload in the
        // listener's `finally` clears locallyAppliedIds, so the value is empty either way.
        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()

        logic.actions.setApplying(['someone-elses-suggestion'], true)
        await expectLogic(logic, () =>
            logic.actions.applyOps(
                [{ op: 'remove_custom_source_mapping', integration: 'MetaAds', raw_utm_source: 'fb-ads' }],
                { label: 'Undone', source: 'setup_tab' }
            )
        )
            .toDispatchActions([
                (action) => action.type === logic.actionTypes.markApplied && action.payload.ids.length === 0,
            ])
            .toFinishAllListeners()
    })

    it('refreshes the sibling logics that would otherwise go stale', async () => {
        // apply_setup_ops writes config server-side, bypassing updateCurrentTeam. If
        // these don't fire, the manual settings sections show stale data right next to
        // the suggestion that just changed it — which reads as a bug.
        await expectLogic(logic, () => logic.actions.applySuggestion(suggestion())).toDispatchActions([
            'loadSetupPlan',
            'loadCurrentTeam',
            marketingAnalyticsSettingsLogic.actionTypes.loadMarketingAnalyticsConfig,
            'loadAuditData',
        ])
    })

    it('undoes by POSTing the server-computed inverse', async () => {
        await expectLogic(logic, () =>
            logic.actions.applyOps(UNDO_OPS, { label: 'Undone', source: 'setup_tab' })
        ).toFinishAllListeners()

        expect(applyRequests[0].ops).toEqual(UNDO_OPS)
    })

    it('batches only the safe suggestions', async () => {
        const unsafe = suggestion({ id: 'unsafe', safe_to_batch: false })
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': () => [200, plan([suggestion(), unsafe])],
            },
        })

        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        expect(logic.values.safeBatch.map((s) => s.id)).toEqual([suggestion().id])

        await expectLogic(logic, () => logic.actions.applyAllSafe()).toFinishAllListeners()
        expect(applyRequests[0].ops).toEqual([suggestion().apply])
        // `source` is recorded against the change server-side, so a one-item batch still
        // has to report where the click came from rather than being inferred from length.
        expect(applyRequests[0].source).toEqual('apply_all_safe')
    })

    it('clears the safe batch once the applied suggestion leaves the plan', async () => {
        // Reported symptom: apply the batch, and "Apply 1 safe" is still there. The
        // count is derived from the reloaded plan, so this pins the whole cycle —
        // apply, reload, recount — rather than any one step of it.
        let loads = 0
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': () => {
                    loads += 1
                    return [200, loads === 1 ? plan([suggestion()]) : plan([])]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        expect(logic.values.safeBatch).toHaveLength(1)

        await expectLogic(logic, () => logic.actions.confirmReviewedBatch(logic.values.safeBatch))
            .toFinishAllListeners()
            .toFinishAllListeners()

        expect(logic.values.safeBatch).toHaveLength(0)
    })

    it('keeps the batch visible when applying fails', async () => {
        // The opposite guarantee: a failed apply must not hide the row, or the user
        // thinks it worked. This is the shape the reported bug would take if the
        // request were 400ing.
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/apply_setup_ops': () => [400, { ops: 'nope' }],
            },
        })

        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.confirmReviewedBatch(logic.values.safeBatch))
            .toFinishAllListeners()
            .toFinishAllListeners()

        expect(logic.values.safeBatch).toHaveLength(1)
    })

    it('skips the audit reload for ops the audit cannot see', async () => {
        // The audit reruns the campaign and UTM-catalogue ClickHouse queries the plan just
        // ran. A conversion-goal change moves neither, so reloading it pays twice for a
        // scan whose answer can't have changed.
        await expectLogic(logic, () =>
            logic.actions.applySuggestion(
                suggestion({
                    id: 'mark_goal_as_revenue:sign_up',
                    kind: 'mark_goal_as_revenue',
                    apply: { op: 'update_conversion_goal', conversion_goal_id: 'abc', patch: {} },
                })
            )
        )
            .toDispatchActions(['loadSetupPlan'])
            .toNotHaveDispatchedActions(['loadAuditData'])
            .toFinishAllListeners()
    })

    it('keeps the review modal open when applying fails', async () => {
        // The reducers used to close on `loadSetupPlanSuccess`, which the listener fires
        // from `finally` — so the reload succeeding closed the modal even though the apply
        // had failed, losing the error and the retry.
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/apply_setup_ops': () => [400, { ops: 'nope' }],
            },
        })

        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewSuggestion(suggestion())).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.confirmReviewedSuggestion(suggestion())).toFinishAllListeners()

        expect(logic.values.reviewingSuggestion).not.toBeNull()
    })

    it('closes the review modal once the apply lands', async () => {
        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.reviewSuggestion(suggestion())).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.confirmReviewedSuggestion(suggestion())).toFinishAllListeners()

        expect(logic.values.reviewingSuggestion).toBeNull()
    })

    it('does not apply a suggestion with no op', async () => {
        await expectLogic(logic, () =>
            logic.actions.applySuggestion(suggestion({ apply: null }))
        ).toFinishAllListeners()

        expect(applyRequests).toHaveLength(0)
    })

    it('hides a dismissed suggestion without applying anything', async () => {
        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()

        logic.actions.dismissSuggestion(suggestion().id)

        expect(logic.values.visibleSuggestions).toHaveLength(0)
        expect(applyRequests).toHaveLength(0)
    })

    describe('reviewing what was dismissed', () => {
        beforeEach(async () => {
            await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
            logic.actions.dismissSuggestion(suggestion().id)
        })

        it('keeps dismissed rows reachable instead of only counting them', () => {
            // Dismissing used to be a one-way door: a count, and no way to see or undo
            // what was behind it.
            expect(logic.values.dismissedSuggestions.map((s) => s.id)).toEqual([suggestion().id])
        })

        it('restores one back into the list', () => {
            logic.actions.restoreSuggestion(suggestion().id)

            expect(logic.values.visibleSuggestions).toHaveLength(1)
            expect(logic.values.dismissedSuggestions).toHaveLength(0)
        })

        it('restores all at once', () => {
            logic.actions.restoreAllDismissed()

            expect(logic.values.dismissedIds).toEqual([])
            expect(logic.values.visibleSuggestions).toHaveLength(1)
        })

        it('does not count a dismissal whose finding is gone', async () => {
            // `dismissedIds` is persisted, so its ids outlive the findings: dismiss a
            // broken sync, fix the sync, and the id sits in localStorage forever.
            // Counting it would advertise hidden work that no longer exists.
            useMocks({
                get: {
                    '/api/projects/:team_id/marketing_analytics/setup_plan': () => [200, plan([])],
                },
            })

            await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()

            expect(logic.values.dismissedIds).toEqual([suggestion().id])
            expect(logic.values.dismissedSuggestions).toEqual([])
        })
    })

    it('asks the server for a fresh scan only when the user asks for one', async () => {
        // The mount-time load is happy with the server's short cache — that's what
        // stops section navigation re-running six ClickHouse queries. An explicit
        // Rescan has to bypass it or the button looks broken.
        const urls: string[] = []
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': ({ request }) => {
                    urls.push(request.url)
                    return [200, plan([])]
                },
            },
        })

        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadSetupPlan({ refresh: true })).toFinishAllListeners()

        expect(urls[0]).not.toContain('refresh')
        expect(urls[1]).toContain('refresh=true')
    })

    describe('retrying syncs', () => {
        const TARGETS = [
            { source_id: 'src-a', display_name: 'Google Ads' },
            { source_id: 'src-b', display_name: 'Meta Ads' },
            { source_id: 'src-c', display_name: 'Bing Ads' },
        ]
        const collapsed = (): Suggestion =>
            suggestion({
                id: 'fix_sync:cause:stale',
                kind: 'fix_sync',
                apply: { op: 'retry_syncs', sources: TARGETS },
            })

        let reloaded: string[]
        let failing: string[]

        beforeEach(() => {
            reloaded = []
            failing = []
            useMocks({
                post: {
                    '/api/environments/:team_id/external_data_sources/:id/reload': (req: any) => {
                        const id = req.params.id as string
                        reloaded.push(id)
                        return failing.includes(id) ? [500, { detail: 'nope' }] : [200, {}]
                    },
                },
            })
        })

        it('reloads every source in the collapsed group', async () => {
            await expectLogic(logic, () => logic.actions.confirmReviewedSuggestion(collapsed())).toFinishAllListeners()

            expect(reloaded).toEqual(['src-a', 'src-b', 'src-c'])
            // Never through apply_setup_ops: the warehouse owns this action and its
            // permissions, and that endpoint only mutates marketing config.
            expect(applyRequests).toHaveLength(0)
        })

        it('keeps going when one source fails', async () => {
            // Independent sources. Stopping at the first error would leave the group
            // half-retried with nothing saying which half.
            failing = ['src-b']

            await expectLogic(logic, () => logic.actions.confirmReviewedSuggestion(collapsed())).toFinishAllListeners()

            expect(reloaded).toEqual(['src-a', 'src-b', 'src-c'])
        })

        it('still handles a single-source retry through the same path', async () => {
            const single = suggestion({
                id: 'fix_sync:google_ads',
                apply: { op: 'retry_sync', source_id: 'src-a', display_name: 'Google Ads' },
            })

            await expectLogic(logic, () => logic.actions.confirmReviewedSuggestion(single)).toFinishAllListeners()

            expect(reloaded).toEqual(['src-a'])
        })
    })

    it('clears the optimistic list on reload so the server view wins', async () => {
        await expectLogic(logic, () => logic.actions.applySuggestion(suggestion())).toFinishAllListeners()

        expect(logic.values.locallyAppliedIds).toEqual([])
    })

    describe('focusing a capability', () => {
        const cost = suggestion({ id: 'fix_sync:google_ads', unlocks: ['cost', 'roas'] })
        const attribution = suggestion({ id: 'add_source_mapping:x', unlocks: ['attribution'] })

        beforeEach(async () => {
            useMocks({
                get: {
                    '/api/projects/:team_id/marketing_analytics/setup_plan': () => [200, plan([cost, attribution])],
                },
            })
            await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()
        })

        it('narrows the list to what changes that metric', () => {
            logic.actions.focusCapability('roas')

            expect(logic.values.listedSuggestions.map((s) => s.id)).toEqual([cost.id])
        })

        it('leaves the section views alone', () => {
            // The nav badges and per-section blocks read `visibleSuggestions`. A filter
            // chosen in Suggested setup emptying the Sources section would read as data
            // loss, not as a filter.
            logic.actions.focusCapability('roas')

            expect(logic.values.visibleSuggestions).toHaveLength(2)
        })

        it('clears when the same chip is clicked again', () => {
            logic.actions.focusCapability('roas')
            logic.actions.focusCapability('roas')

            expect(logic.values.focusedCapability).toBeNull()
            expect(logic.values.listedSuggestions).toHaveLength(2)
        })

        it('drops the filter on rescan', async () => {
            logic.actions.focusCapability('roas')

            await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()

            // A rescan can remove the capability entirely; holding the filter across it
            // leaves an empty list with nothing on screen explaining why.
            expect(logic.values.focusedCapability).toBeNull()
        })
    })

    it('surfaces degraded and truncated from the response', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': () => [
                    200,
                    { ...plan([]), degraded: ['attribution_health'], truncated: true },
                ],
            },
        })

        await expectLogic(logic, () => logic.actions.loadSetupPlan()).toFinishAllListeners()

        expect(logic.values.degraded).toEqual(['attribution_health'])
        expect(logic.values.truncated).toBe(true)
    })
})
