import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'
import { productSelectionLogic } from './productSelection/productSelectionLogic'
import { INSTALL_DEDUP_KEYS } from './types'

/**
 * Comprehensive coverage of the onboarding flow composition system. The flow selector
 * is the central piece of the refactor and the place where regressions are most costly
 * (wrong steps, missed dedup, mis-ordered installs, lost completion bookkeeping).
 *
 * Test focus:
 *   1. Flow shape per single product and representative multi-product combos
 *   2. Install-step dedup behaviour (POSTHOG_JS, OPENTELEMETRY, no-dedup)
 *   3. Bucket sort: all installs first, the primary product's install first among them
 *   4. URL parsing defenses (cap, dedupe, filter)
 *   5. Navigation correctness (next/prev, bad stepId reconciliation)
 *   6. Completion: visited-product credit, idempotency, additionalProductKeys merge
 */
describe('onboardingLogic — flow composition', () => {
    let logic: ReturnType<typeof onboardingLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = onboardingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    /** Convenience: list step ids for the active flow. */
    const flowIds = (): string[] => logic.values.flow.map((s) => s.id)
    /** Convenience: list step keys for the active flow. */
    const flowStepKeys = (): OnboardingStepKey[] => logic.values.flow.map((s) => s.stepKey)

    describe('single-product flows', () => {
        // Each entry: [primaryProduct, expected step ids in order].
        // Default test environment has the user as Admin (canInviteTeammates=true) and
        // billing not loaded (shouldShowBillingStep=false), so flows include the invite
        // step but not the plans step. Bucket sort puts the install step first.
        const cases: Array<[ProductKey, string[]]> = [
            [
                ProductKey.PRODUCT_ANALYTICS,
                [
                    'install:product_analytics',
                    'configure:product_analytics',
                    'session_replay:product_analytics',
                    'link_data:product_analytics',
                    'invite_teammates:product_analytics',
                ],
            ],
            [
                ProductKey.WEB_ANALYTICS,
                [
                    'install:web_analytics',
                    'authorized_domains:web_analytics',
                    'configure:web_analytics',
                    'invite_teammates:web_analytics',
                ],
            ],
            [
                ProductKey.SESSION_REPLAY,
                ['install:session_replay', 'configure:session_replay', 'invite_teammates:session_replay'],
            ],
            [ProductKey.FEATURE_FLAGS, ['install:feature_flags', 'invite_teammates:feature_flags']],
            [ProductKey.EXPERIMENTS, ['install:experiments', 'invite_teammates:experiments']],
            [ProductKey.SURVEYS, ['install:surveys', 'invite_teammates:surveys']],
            [
                ProductKey.ERROR_TRACKING,
                [
                    'install:error_tracking',
                    'source_maps:error_tracking',
                    'alerts:error_tracking',
                    'invite_teammates:error_tracking',
                ],
            ],
            [ProductKey.AI_OBSERVABILITY, ['install:llm_analytics', 'invite_teammates:llm_analytics']],
            [ProductKey.WORKFLOWS, ['install:workflows', 'invite_teammates:workflows']],
            [ProductKey.LOGS, ['install:logs', 'invite_teammates:logs']],
            // Data Warehouse has no install step — the link_data step is the entry point.
            [ProductKey.DATA_WAREHOUSE, ['link_data:data_warehouse', 'invite_teammates:data_warehouse']],
            // Support has no product-specific step; it's enabled on completion, so only the shared step shows.
            [ProductKey.CONVERSATIONS, ['invite_teammates:conversations']],
        ]

        it.each(cases)('builds the expected flow when only %s is selected', (product, expected) => {
            logic.actions.setProductKey(product)
            expect(flowIds()).toEqual(expected)
        })

        it('returns an empty flow when no product is selected', () => {
            expect(logic.values.flow).toEqual([])
            expect(logic.values.currentFlowStep).toBeNull()
        })

        it('includes the web analytics path cleaning step only when its flag is enabled', () => {
            featureFlagLogic
                .findMounted()
                ?.actions.setFeatureFlags([FEATURE_FLAGS.WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS], {
                    [FEATURE_FLAGS.WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS]: true,
                })
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            expect(flowIds()).toContain('path_cleaning:web_analytics')
        })
    })

    describe('install-step dedup — POSTHOG_JS', () => {
        it('collapses two posthog-js installs into one survivor (PA primary + WA secondary)', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.WEB_ANALYTICS])

            const installs = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.INSTALL)
            expect(installs).toHaveLength(1)
            expect(installs[0].id).toBe('install:product_analytics')
            expect(installs[0].dedupKey).toBe(INSTALL_DEDUP_KEYS.POSTHOG_JS)
        })

        it('credits dropped products via additionalProductKeys', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([
                ProductKey.WEB_ANALYTICS,
                ProductKey.SESSION_REPLAY,
                ProductKey.FEATURE_FLAGS,
            ])

            const survivor = logic.values.flow.find((s) => s.id === 'install:product_analytics')!
            expect(survivor.additionalProductKeys).toEqual(
                expect.arrayContaining([
                    ProductKey.PRODUCT_ANALYTICS,
                    ProductKey.WEB_ANALYTICS,
                    ProductKey.SESSION_REPLAY,
                    ProductKey.FEATURE_FLAGS,
                ])
            )
        })

        it('merges dropped setup task ids that differ from the survivor (SR.SetupSessionRecordings, ET.EnableErrorTracking)', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.SESSION_REPLAY, ProductKey.ERROR_TRACKING])

            const survivor = logic.values.flow.find((s) => s.id === 'install:product_analytics')!
            // Survivor's own setupTaskId is `IngestFirstEvent`; dropped descriptors contribute
            // their own task ids, which may include `IngestFirstEvent` from sibling posthog-js
            // products (deduped against the survivor's own). The exact set depends on which
            // products are picked — we assert the distinctive ones.
            expect(survivor.additionalSetupTaskIds).toEqual(
                expect.arrayContaining([SetupTaskId.SetupSessionRecordings, SetupTaskId.EnableErrorTracking])
            )
        })

        it('all 7 posthog-js products yield exactly one install step', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([
                ProductKey.WEB_ANALYTICS,
                ProductKey.SESSION_REPLAY,
                ProductKey.FEATURE_FLAGS,
                ProductKey.EXPERIMENTS,
                ProductKey.SURVEYS,
                ProductKey.ERROR_TRACKING,
            ])

            const installs = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.INSTALL)
            expect(installs).toHaveLength(1)
            expect(installs[0].dedupKey).toBe(INSTALL_DEDUP_KEYS.POSTHOG_JS)
        })

        it('does not attach extras when only the primary contributes (no other products in dedup group)', () => {
            // PA alone has dedupKey POSTHOG_JS but no other posthog-js product to merge with.
            // Survivor should NOT carry additionalProductKeys / additionalSetupTaskIds since
            // there's nothing to add (productKeys.length === 1, setupTaskIds.length === 0).
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            const survivor = logic.values.flow.find((s) => s.id === 'install:product_analytics')!
            expect(survivor.additionalProductKeys).toBeUndefined()
            expect(survivor.additionalSetupTaskIds).toBeUndefined()
        })
    })

    describe('install-step dedup — OPENTELEMETRY', () => {
        it('Logs install uses the OTEL dedup key (separate group from posthog-js)', () => {
            logic.actions.setProductKey(ProductKey.LOGS)
            const install = logic.values.flow.find((s) => s.stepKey === OnboardingStepKey.INSTALL)!
            expect(install.dedupKey).toBe(INSTALL_DEDUP_KEYS.OPENTELEMETRY)
        })

        it('PA primary + Logs secondary keeps both install steps (different dedup groups)', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.LOGS])

            const installs = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.INSTALL)
            expect(installs).toHaveLength(2)
            expect(installs.map((s) => s.dedupKey)).toEqual([
                INSTALL_DEDUP_KEYS.POSTHOG_JS,
                INSTALL_DEDUP_KEYS.OPENTELEMETRY,
            ])
        })

        // Metrics and Logs both send over OTel, but their install steps are NOT
        // functionally identical (Metrics is OTLP/scrape-agent only; Logs offers 10
        // SDK-specific flows). Collapsing them would drop the loser's instruction map,
        // so picking both must keep both install steps regardless of which is primary.
        it('Metrics primary + Logs secondary keeps both install steps (no dedup)', () => {
            logic.actions.setProductKey(ProductKey.METRICS)
            logic.actions.setSecondaryProductKeys([ProductKey.LOGS])

            const installs = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.INSTALL)
            expect(installs.map((s) => s.id)).toEqual(['install:metrics', 'install:logs'])
        })
    })

    describe('install-step — no dedup', () => {
        it('AI observability + Workflows produce two install steps (neither has a dedupKey)', () => {
            logic.actions.setProductKey(ProductKey.AI_OBSERVABILITY)
            logic.actions.setSecondaryProductKeys([ProductKey.WORKFLOWS])

            const installs = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.INSTALL)
            expect(installs).toHaveLength(2)
            expect(installs.every((s) => s.dedupKey === undefined)).toBe(true)
        })

        it('PA + LLM + Workflows + Logs yields four install steps (PA dedup, LLM, WF, LOGS dedup)', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.AI_OBSERVABILITY, ProductKey.WORKFLOWS, ProductKey.LOGS])

            const installs = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.INSTALL)
            expect(installs.map((s) => s.id)).toEqual([
                'install:product_analytics',
                'install:llm_analytics',
                'install:workflows',
                'install:logs',
            ])
        })
    })

    describe('step ordering (bucket sort)', () => {
        it('puts the posthog-js install first (bucket 0) for a multi-step PA primary flow', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            // PA emits: install, product_configuration, session_replay (configure)
            // sharedSteps appends: link_data, invite_teammates
            // After bucket sort: install (bucket 0) MUST be first.
            expect(logic.values.flow[0].id).toBe('install:product_analytics')
        })

        it('all install steps come before any non-install step', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.AI_OBSERVABILITY, ProductKey.WORKFLOWS, ProductKey.LOGS])

            const lastInstallIdx = logic.values.flow
                .map((s, i) => (s.stepKey === OnboardingStepKey.INSTALL ? i : -1))
                .filter((i) => i >= 0)
                .pop()
            const firstNonInstallIdx = logic.values.flow.findIndex((s) => s.stepKey !== OnboardingStepKey.INSTALL)
            expect(lastInstallIdx!).toBeLessThan(firstNonInstallIdx)
        })

        it('non-install steps preserve their relative order after bucket sort (stable)', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            // PA's intra-product order is: install → product_configuration → session_replay.
            // sharedSteps appends link_data, invite_teammates AFTER. Bucket sort moves
            // install to position 0; the rest must keep their relative order.
            const nonInstall = logic.values.flow.filter((s) => s.stepKey !== OnboardingStepKey.INSTALL)
            expect(nonInstall.map((s) => s.stepKey)).toEqual([
                OnboardingStepKey.PRODUCT_CONFIGURATION, // 'configure'
                OnboardingStepKey.SESSION_REPLAY,
                OnboardingStepKey.LINK_DATA,
                OnboardingStepKey.INVITE_TEAMMATES,
            ])
        })

        it('non-posthog-js install steps land in bucket 1 (after posthog-js install, before non-installs)', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.LOGS])

            const ids = flowIds()
            const paInstallIdx = ids.indexOf('install:product_analytics')
            const logsInstallIdx = ids.indexOf('install:logs')
            const firstNonInstall = logic.values.flow.findIndex((s) => s.stepKey !== OnboardingStepKey.INSTALL)
            expect(paInstallIdx).toBe(0)
            expect(logsInstallIdx).toBe(1)
            expect(firstNonInstall).toBeGreaterThan(logsInstallIdx)
        })

        it('puts the primary product install first, even when a posthog-js install is secondary', () => {
            // "Monitor AI applications" use case → AI observability + product analytics.
            // When the user picks AI observability as the "Start with" product, its install
            // (which has no posthog-js dedup key) must render before the product analytics
            // install — the primary choice decides ordering, not the SDK.
            logic.actions.setProductKey(ProductKey.AI_OBSERVABILITY)
            logic.actions.setSecondaryProductKeys([ProductKey.PRODUCT_ANALYTICS])

            const ids = flowIds()
            expect(ids.indexOf('install:llm_analytics')).toBe(0)
            expect(ids.indexOf('install:llm_analytics')).toBeLessThan(ids.indexOf('install:product_analytics'))
        })
    })

    describe('shared trailing steps', () => {
        it('appends data-warehouse step for PA primary when DW is not in secondaries', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            const linkDataSteps = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.LINK_DATA)
            expect(linkDataSteps).toHaveLength(1)
            expect(linkDataSteps[0].productKey).toBe(ProductKey.PRODUCT_ANALYTICS)
        })

        it('does NOT duplicate data-warehouse step when DW is also in secondaries', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.DATA_WAREHOUSE])
            const linkDataSteps = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.LINK_DATA)
            // DW provider's link_data emits once; sharedSteps' append is suppressed by the
            // `secondaries.includes(DATA_WAREHOUSE)` check. Without that guard the user would
            // walk through Import data twice.
            expect(linkDataSteps).toHaveLength(1)
            expect(linkDataSteps[0].productKey).toBe(ProductKey.DATA_WAREHOUSE)
        })

        it('does NOT append data-warehouse step for non-PA primaries', () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            const linkDataSteps = logic.values.flow.filter((s) => s.stepKey === OnboardingStepKey.LINK_DATA)
            expect(linkDataSteps).toHaveLength(0)
        })

        it('appends invite-teammates step when canInviteTeammates is true (default Admin user)', () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            const invite = logic.values.flow.find((s) => s.stepKey === OnboardingStepKey.INVITE_TEAMMATES)
            expect(invite).not.toBeUndefined()
            expect(invite!.productKey).toBe(ProductKey.WEB_ANALYTICS)
        })
    })

    describe('currentFlowStep selector', () => {
        it('falls through to flow[0] when stepId is empty', () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            expect(logic.values.currentFlowStep?.id).toBe('install:web_analytics')
        })

        it('resolves an exact namespaced id', () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            logic.actions.setStepId('authorized_domains:web_analytics')
            expect(logic.values.currentFlowStep?.id).toBe('authorized_domains:web_analytics')
        })

        it('resolves a bare stepKey via loose match (legacy URL support)', () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            logic.actions.setStepId('authorized_domains')
            // First descriptor matching stepKey === 'authorized_domains'.
            expect(logic.values.currentFlowStep?.stepKey).toBe(OnboardingStepKey.AUTHORIZED_DOMAINS)
        })

        it('returns null and self-corrects to flow[0] for an unresolvable stepId', async () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            // The setStepId listener detects the bad id and dispatches setStepId('') as
            // self-correction once flow.length > 0. We assert the end state rather than
            // the intermediate dispatches — the contract is "user lands on flow[0],
            // URL doesn't keep a stale stepId" regardless of how many setStepId calls
            // it takes to get there.
            logic.actions.setStepId('totally-bogus-step')
            // Flush microtasks so the self-correcting setStepId('') has a chance to run.
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(logic.values.stepId).toBe('')
            expect(logic.values.currentFlowStep?.id).toBe('install:web_analytics')
        })

        it('self-corrects a valid step key the flow has no step for', async () => {
            // Product selection always routes to ?step=install, but Support's flow has no
            // install step, so a key being valid is not reason enough to keep waiting on it.
            logic.actions.setProductKey(ProductKey.CONVERSATIONS)
            logic.actions.setStepId(OnboardingStepKey.INSTALL)
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(logic.values.stepId).toBe('')
            expect(logic.values.currentFlowStep?.id).toBe('invite_teammates:conversations')
        })

        it('self-corrects link_data when the flow will never carry it', async () => {
            // `link_data` is gated on the product keys alone, which are set before the step is,
            // so for a primary that never gets it there is nothing to wait for.
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            logic.actions.setStepId(OnboardingStepKey.LINK_DATA)
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(logic.values.stepId).toBe('')
            expect(logic.values.currentFlowStep?.id).toBe('install:web_analytics')
        })

        it('holds a shared trailing step open until it is appended', async () => {
            // `plans` joins the flow only once billing loads, which it has not here.
            // Self-correcting it would lose the request before the flow settles.
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            logic.actions.setStepId(OnboardingStepKey.PLANS)
            await new Promise((resolve) => setTimeout(resolve, 0))
            expect(logic.values.stepId).toBe(OnboardingStepKey.PLANS)
        })
    })

    describe('navigation', () => {
        it('goToNextStep advances to the next descriptor by id', async () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            await expectLogic(logic, () => {
                logic.actions.goToNextStep()
            }).toDispatchActions([
                { type: logic.actionTypes.setStepId, payload: { stepId: 'authorized_domains:web_analytics' } },
            ])
        })

        it('goToNextStep on the last step calls completeOnboarding', async () => {
            logic.actions.setProductKey(ProductKey.SURVEYS)
            const lastId = logic.values.flow[logic.values.flow.length - 1].id
            logic.actions.setStepId(lastId)
            await expectLogic(logic, () => {
                logic.actions.goToNextStep()
            }).toDispatchActions(['completeOnboarding'])
        })

        it('goToPreviousStep at index 0 is a no-op', async () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            // setStepId('') resolves to flow[0] via currentFlowStep fallback.
            await expectLogic(logic, () => {
                logic.actions.goToPreviousStep()
            }).toNotHaveDispatchedActions(['setStepId'])
        })

        it('goToNextStep is a no-op when no product is selected (empty flow)', async () => {
            await expectLogic(logic, () => {
                logic.actions.goToNextStep()
            }).toNotHaveDispatchedActions(['completeOnboarding'])
        })
    })

    describe('visited-step tracking', () => {
        it('forward jump via setStepId marks every traversed step as visited', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setStepId('install:product_analytics')
            logic.actions.setStepId('link_data:product_analytics')
            // PA flow after bucket sort: install, product_configuration, session_replay,
            // link_data, invite_teammates. Forward jump install → link_data should mark
            // every step from install up to link_data inclusive.
            expect(logic.values.visitedStepIds).toEqual(
                expect.arrayContaining([
                    'install:product_analytics',
                    'configure:product_analytics',
                    'session_replay:product_analytics',
                    'link_data:product_analytics',
                ])
            )
        })

        it('backward jump does not unmark already-visited steps', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setStepId('install:product_analytics')
            logic.actions.setStepId('link_data:product_analytics')
            const afterForward = [...logic.values.visitedStepIds]
            logic.actions.setStepId('install:product_analytics')
            // Set semantics: visitedStepIds is monotonic — backward navigation never removes.
            expect(logic.values.visitedStepIds).toEqual(expect.arrayContaining(afterForward))
        })
    })

    describe('completeOnboarding — visited-product credit', () => {
        it('credits the primary product even when only its first step was visited (deep-link backfill at completion)', async () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            await expectLogic(logic, () => {
                logic.actions.completeOnboarding()
            }).toDispatchActions([
                {
                    type: logic.actionTypes.recordProductIntentOnboardingComplete,
                    payload: { product_type: ProductKey.PRODUCT_ANALYTICS } as any,
                },
                (action) => {
                    if (action.type !== logic.actionTypes.updateCurrentTeam) {
                        return false
                    }
                    expect(action.payload).toMatchObject({
                        completed_snippet_onboarding: true,
                        has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
                    })
                    return true
                },
            ])
        })

        it('credits dedup-collapsed secondaries via additionalProductKeys at completion', async () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.WEB_ANALYTICS, ProductKey.SESSION_REPLAY])
            // Survivor descriptor carries additionalProductKeys=[PA, WA, SR]; the
            // completion listener iterates them and dispatches
            // `recordProductIntentOnboardingComplete` for each. We collect every
            // dispatched product_type and assert the full set, since the iteration
            // order is `Set` insertion order (primary first, then per-step adds).
            logic.actions.setStepId('install:product_analytics')
            const dispatched: ProductKey[] = []
            await expectLogic(logic, () => {
                logic.actions.completeOnboarding()
            }).toDispatchActions([
                'completeOnboarding',
                (action) => {
                    if (action.type === logic.actionTypes.recordProductIntentOnboardingComplete) {
                        dispatched.push((action.payload as any).product_type)
                    }
                    // Stop matching once we've seen the team update — that's the tail
                    // of the synchronous completion path.
                    return action.type === logic.actionTypes.updateCurrentTeam
                },
            ])
            expect(dispatched).toEqual(
                expect.arrayContaining([
                    ProductKey.PRODUCT_ANALYTICS,
                    ProductKey.WEB_ANALYTICS,
                    ProductKey.SESSION_REPLAY,
                ])
            )
        })

        it('is idempotent — short-circuits when isCompleting is already true (isCompleting guard)', async () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            // Set the guard directly to test the guard's effect deterministically. (Going
            // through a real first `completeOnboarding()` then checking the second is
            // racy: the team-patch failure in jsdom resets `isCompleting` async, which
            // can flip back to false before the second call lands.)
            logic.actions.setIsCompleting(true)

            await expectLogic(logic, () => {
                logic.actions.completeOnboarding()
            }).toNotHaveDispatchedActions(['recordProductIntentOnboardingComplete'])
        })

        it('returns early when no productKey is set', async () => {
            await expectLogic(logic, () => {
                logic.actions.completeOnboarding()
            }).toNotHaveDispatchedActions(['recordProductIntentOnboardingComplete', 'setIsCompleting'])
        })
    })

    describe('URL → state', () => {
        it('parses /onboarding/<productKey> and sets primary', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/onboarding/web_analytics')
            }).toDispatchActions([
                { type: logic.actionTypes.setProductKey, payload: { productKey: ProductKey.WEB_ANALYTICS } as any },
            ])
            expect(logic.values.productKey).toBe(ProductKey.WEB_ANALYTICS)
        })

        it('parses ?with= as a CSV of secondary products', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/onboarding/web_analytics?with=logs,product_analytics')
            }).toDispatchActions(['setSecondaryProductKeys'])
            expect(logic.values.secondaryProductKeys).toEqual([ProductKey.LOGS, ProductKey.PRODUCT_ANALYTICS])
        })

        it('filters the primary product out of ?with= (avoids self-secondary)', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/onboarding/web_analytics?with=web_analytics,logs')
            }).toDispatchActions(['setSecondaryProductKeys'])
            expect(logic.values.secondaryProductKeys).toEqual([ProductKey.LOGS])
        })

        it('drops unknown product keys from ?with=', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/onboarding/web_analytics?with=invalid_product,logs,another_invalid')
            }).toDispatchActions(['setSecondaryProductKeys'])
            expect(logic.values.secondaryProductKeys).toEqual([ProductKey.LOGS])
        })

        it('dedupes ?with= and caps the result at MAX_WITH_PRODUCTS (16)', async () => {
            // Stuff the head with duplicates plus extra valid keys; only one of each survives,
            // and the total is capped at 16. We use 8 valid keys + 16 duplicates of the first.
            const valid = [
                ProductKey.LOGS,
                ProductKey.PRODUCT_ANALYTICS,
                ProductKey.SESSION_REPLAY,
                ProductKey.FEATURE_FLAGS,
                ProductKey.EXPERIMENTS,
                ProductKey.SURVEYS,
                ProductKey.ERROR_TRACKING,
                ProductKey.AI_OBSERVABILITY,
            ]
            const stuffed = [...Array(16).fill(ProductKey.LOGS), ...valid].join(',')
            await expectLogic(logic, () => {
                router.actions.push(`/onboarding/web_analytics?with=${stuffed}`)
            }).toDispatchActions(['setSecondaryProductKeys'])
            expect(logic.values.secondaryProductKeys.length).toBeLessThanOrEqual(16)
            // Each valid key survives the dedupe-before-truncate.
            for (const key of valid) {
                expect(logic.values.secondaryProductKeys).toContain(key)
            }
        })

        it('parses ?step= as the namespaced step id', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/onboarding/web_analytics?step=authorized_domains:web_analytics')
            }).toDispatchActions(['setStepId'])
            expect(logic.values.stepId).toBe('authorized_domains:web_analytics')
        })

        it('keeps passthrough params separate from ?step= when navigating (GitHub-callback params)', async () => {
            // The GitHub App install callback returns to onboarding with extra query params
            // (integration_id, installation_id). Advancing a step must keep them as separate
            // params — a naive path+search concat fused them into the step value
            // (step=configure:x?integration_id=14), which no flow step resolves, leaving the
            // host on a spinner forever.
            router.actions.push('/onboarding/product_analytics?step=install:product_analytics&integration_id=14')
            await expectLogic(logic).toDispatchActions(['setStepId'])
            await expectLogic(logic, () => {
                logic.actions.goToNextStep()
            }).toDispatchActions(['setStepId'])
            expect(router.values.searchParams).toMatchObject({
                step: 'configure:product_analytics',
                integration_id: 14,
            })
            expect(logic.values.currentFlowStep?.id).toBe('configure:product_analytics')
        })

        it('self-corrects a step id with fused query params instead of treating it as namespaced', async () => {
            router.actions.push(
                `/onboarding/product_analytics?step=${encodeURIComponent('configure:product_analytics?integration_id=14')}`
            )
            await expectLogic(logic).toDispatchActions(['setStepId'])
            // The mangled id contains ':' but must not count as a known step key — it resolves
            // to '' (flow[0]) rather than leaving currentFlowStep null and the host spinning.
            expect(logic.values.stepId).toBe('')
            expect(logic.values.currentFlowStep?.id).toBe('install:product_analytics')
        })

        it('sets subscribedDuringOnboarding when ?success=true is present', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/onboarding/web_analytics?success=true')
            }).toDispatchActions([
                {
                    type: logic.actionTypes.setSubscribedDuringOnboarding,
                    payload: { subscribedDuringOnboarding: true } as any,
                },
            ])
        })
    })

    describe('completion redirect URL', () => {
        // Each entry: [primary, expected redirect path-substring].
        // Verifies that each per-product provider's `completeRedirectUrl` is wired up.
        // EXPERIMENTS intentionally falls through to urls.default() — same behaviour as
        // the original central switch.
        const cases: Array<[ProductKey, RegExp]> = [
            [ProductKey.PRODUCT_ANALYTICS, /quickstart|insight/i],
            [ProductKey.WEB_ANALYTICS, /web/i],
            [ProductKey.SESSION_REPLAY, /replay/i],
            [ProductKey.FEATURE_FLAGS, /feature-flags/i],
            [ProductKey.SURVEYS, /survey/i],
            [ProductKey.ERROR_TRACKING, /error-tracking/i],
            [ProductKey.AI_OBSERVABILITY, /ai-observability/i],
            [ProductKey.WORKFLOWS, /workflow/i],
            [ProductKey.LOGS, /log/i],
            [ProductKey.DATA_WAREHOUSE, /sources|data-management/i],
            [ProductKey.CONVERSATIONS, /support/i],
        ]

        it.each(cases)('%s lands on a product-specific page', (product, pattern) => {
            logic.actions.setProductKey(product)
            expect(logic.values.onCompleteOnboardingRedirectUrl).toMatch(pattern)
        })

        it('experiments falls through to urls.default()', () => {
            logic.actions.setProductKey(ProductKey.EXPERIMENTS)
            expect(logic.values.onCompleteOnboardingRedirectUrl).toBe('/')
        })

        it('redirect override takes precedence over the per-product URL', () => {
            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            logic.actions.setOnCompleteOnboardingRedirectUrl('/custom-target')
            expect(logic.values.onCompleteOnboardingRedirectUrl).toBe('/custom-target')
        })
    })

    describe('completion redirect', () => {
        const completeProduct = (): void => {
            const completed = { has_completed_onboarding_for: { product_analytics: true } }
            logic.actions.updateCurrentTeamSuccess(completed as any, completed as any)
        }

        it('redirects to the product once onboarding completes', async () => {
            router.actions.push(urls.default())
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            await expectLogic(logic, () => {
                completeProduct()
            }).toFinishAllListeners()
            expect(router.values.location.pathname).toMatch(/quickstart|insight/i)
        })
    })

    describe('flow variants', () => {
        const assignSimpleFlowArm = (variant: string): void => {
            featureFlagLogic.findMounted()?.actions.setFeatureFlags([FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW], {
                [FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW]: variant,
            })
        }

        const currentPath = (): string => removeProjectIdIfPresent(router.values.location.pathname)

        it.each([
            ['test arm', 'test', '/onboarding', false, '/onboarding/simple', 'simple', ['simple']],
            ['test arm with late flags', 'test', '/onboarding', true, '/onboarding/simple', 'simple', ['simple']],
            ['control arm', 'control', '/onboarding', false, '/onboarding', 'default', ['legacy']],
            [
                'test arm on a product url',
                'test',
                '/onboarding/product_analytics',
                true,
                '/onboarding/product_analytics',
                'default',
                [],
            ],
        ])(
            '%s lands on the right flow',
            async (_, variant, entryPath, flagsLandLate, pathname, flowVariant, startedFlowVariants) => {
                const capture = jest.spyOn(posthog, 'capture').mockImplementation()
                if (!flagsLandLate) {
                    assignSimpleFlowArm(variant)
                }
                router.actions.push(entryPath)
                // The page renders product selection while it sits on bare `/onboarding`.
                const productSelection = currentPath() === '/onboarding' ? productSelectionLogic() : null
                productSelection?.mount()
                if (flagsLandLate) {
                    assignSimpleFlowArm(variant)
                }
                await expectLogic(logic).toFinishAllListeners()
                productSelection?.unmount()
                expect(currentPath()).toBe(pathname)
                expect(logic.values.flowVariant).toBe(flowVariant)
                const startedVariants = capture.mock.calls
                    .filter(([event]) => event === 'onboarding started')
                    .map(([, properties]) => properties?.flow_variant)
                expect(startedVariants).toEqual(startedFlowVariants)
            }
        )

        it('the simple flow is install, MCP, then invite, and advancing stays on its own URL', async () => {
            router.actions.push(urls.simpleOnboarding())
            await expectLogic(logic).toFinishAllListeners()
            expect(flowIds()).toEqual([
                'install:product_analytics',
                'mcp:product_analytics',
                'invite_teammates:product_analytics',
            ])

            logic.actions.goToNextStep()
            await expectLogic(logic).toFinishAllListeners()
            expect(currentPath()).toBe(urls.simpleOnboarding())
            expect(router.values.searchParams.step).toBe('mcp:product_analytics')
            expect(logic.values.onCompleteOnboardingRedirectUrl).toBe(urls.onboardingWelcome())
            expect(logic.values.installStepReturnUrl).toBe(
                `${urls.simpleOnboarding()}?step=${encodeURIComponent('install:product_analytics')}`
            )
        })

        it.each([
            ['the welcome page', '', OnboardingStepKey.INSTALL, urls.onboardingWelcome()],
            ['the page the user signed up to reach', '?next=%2Finsights', OnboardingStepKey.MCP, '/insights'],
            ['the welcome page from plans', '', OnboardingStepKey.PLANS, urls.onboardingWelcome()],
        ])('skipping the simple flow records the skip before landing on %s', async (_, search, step, landingPath) => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            const skipRequests: unknown[] = []
            useMocks({
                post: {
                    '/api/users/@me/onboarding/skip/': async ({ request }) => {
                        skipRequests.push(await request.json())
                        return [200, {}]
                    },
                },
            })
            router.actions.push(urls.simpleOnboarding() + search)
            logic.actions.setStepId(`${step}:${ProductKey.PRODUCT_ANALYTICS}`)
            await expectLogic(logic).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.skipSimpleOnboarding()
            }).toFinishAllListeners()

            expect(skipRequests).toEqual([{ reason: 'later', step_at_skip: step, flow_variant: 'simple' }])
            expect(currentPath()).toBe(landingPath)
            expect(logic.values.isSkippingOnboarding).toBe(false)
            expect(capture.mock.calls.some(([event]) => event === 'onboarding completed')).toBe(false)
        })

        it('skipping the final invites completes onboarding without sending pending invitations', async () => {
            const capture = jest.spyOn(posthog, 'capture').mockImplementation()
            const skipRequests: unknown[] = []
            useMocks({
                post: {
                    '/api/users/@me/onboarding/skip/': async ({ request }) => {
                        skipRequests.push(await request.json())
                        return [200, {}]
                    },
                },
                patch: {
                    '/api/environments/:team_id/': async ({ request }) => [
                        200,
                        { ...teamLogic.values.currentTeam, ...((await request.json()) as Record<string, unknown>) },
                    ],
                },
            })
            const invites = inviteLogic()
            invites.mount()
            invites.actions.updateInviteAtIndex({ target_email: 'teammate@example.com' }, 0)
            router.actions.push(urls.simpleOnboarding(), { step: 'invite_teammates:product_analytics' })
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.skipSimpleOnboarding()
                logic.actions.skipSimpleOnboarding()
            })
                .toNotHaveDispatchedActions([invites.actionTypes.inviteTeamMembers])
                .toFinishAllListeners()

            expect(currentPath()).toBe(urls.onboardingWelcome())
            expect(teamLogic.values.currentTeam).toMatchObject({
                completed_snippet_onboarding: true,
                has_completed_onboarding_for: { [ProductKey.PRODUCT_ANALYTICS]: true },
            })
            expect(skipRequests).toEqual([])
            expect(capture.mock.calls.filter(([event]) => event === 'onboarding completed')).toEqual([
                [
                    'onboarding completed',
                    expect.objectContaining({ product_key: 'product_analytics', flow_variant: 'simple' }),
                ],
            ])
            expect(capture).toHaveBeenCalledWith('onboarding step skipped', {
                step_key: OnboardingStepKey.INVITE_TEAMMATES,
                product_key: ProductKey.PRODUCT_ANALYTICS,
                flow_variant: 'simple',
                entry_point: 'simple_onboarding',
                version: 1,
            })
            expect(logic.values.isCompleting).toBe(false)
            invites.unmount()
        })

        it.each([OnboardingStepKey.INSTALL, OnboardingStepKey.INVITE_TEAMMATES])(
            'allows retrying a failed exit from %s without navigating away',
            async (step) => {
                let failExit = true
                useMocks({
                    post: { '/api/users/@me/onboarding/skip/': () => [failExit ? 500 : 200, {}] },
                    patch: {
                        '/api/environments/:team_id/': async ({ request }) => [
                            failExit ? 500 : 200,
                            { ...teamLogic.values.currentTeam, ...((await request.json()) as Record<string, unknown>) },
                        ],
                    },
                })
                router.actions.push(urls.simpleOnboarding(), { step: `${step}:product_analytics` })
                await expectLogic(logic).toFinishAllListeners()

                await expectLogic(logic, () => {
                    logic.actions.skipSimpleOnboarding()
                }).toFinishAllListeners()

                expect(currentPath()).toBe(urls.simpleOnboarding())
                expect(logic.values.isCompleting).toBe(false)
                expect(logic.values.isSkippingOnboarding).toBe(false)

                failExit = false
                await expectLogic(logic, () => {
                    logic.actions.skipSimpleOnboarding()
                }).toFinishAllListeners()
                expect(currentPath()).toBe(urls.onboardingWelcome())
            }
        )
    })

    describe('flow stays consistent across product changes', () => {
        it('switching primary resets the secondary list and rebuilds the flow', () => {
            logic.actions.setProductKey(ProductKey.PRODUCT_ANALYTICS)
            logic.actions.setSecondaryProductKeys([ProductKey.LOGS])
            expect(flowIds()).toContain('install:logs')

            logic.actions.setProductKey(ProductKey.WEB_ANALYTICS)
            // Switching primary triggers resetOnboardingFlowState which clears secondaries.
            // The flow now reflects just WA.
            expect(logic.values.secondaryProductKeys).toEqual([])
            expect(flowStepKeys()).not.toContain(OnboardingStepKey.LINK_DATA)
        })
    })
})
