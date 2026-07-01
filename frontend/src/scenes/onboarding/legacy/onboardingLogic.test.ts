import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { OnboardingStepKey } from '~/types'

import { onboardingLogic } from './onboardingLogic'
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
        ]

        it.each(cases)('builds the expected flow when only %s is selected', (product, expected) => {
            logic.actions.setProductKey(product)
            expect(flowIds()).toEqual(expected)
        })

        it('returns an empty flow when no product is selected', () => {
            expect(logic.values.flow).toEqual([])
            expect(logic.values.currentFlowStep).toBeNull()
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
            [ProductKey.FEATURE_FLAGS, /feature_flag/i],
            [ProductKey.SURVEYS, /survey/i],
            [ProductKey.ERROR_TRACKING, /error_tracking/i],
            [ProductKey.AI_OBSERVABILITY, /ai-observability/i],
            [ProductKey.WORKFLOWS, /workflow/i],
            [ProductKey.LOGS, /log/i],
            [ProductKey.DATA_WAREHOUSE, /sources|data-management/i],
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

    describe('onboardingFlowVariant', () => {
        const setVariant = (value: string | boolean | undefined): void => {
            featureFlagLogic
                .findMounted()
                ?.actions.setFeatureFlags(
                    value === undefined ? [] : [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT],
                    value === undefined ? {} : { [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: value }
                )
        }

        it('falls back to legacy when the flag is not set', () => {
            // Default test env sets no feature flags — the missing-flag path must resolve to legacy.
            expect(logic.values.onboardingFlowVariant).toBe('legacy')
        })

        it('falls back to legacy when the flag resolves to a boolean (non-string) value', () => {
            setVariant(true)
            expect(logic.values.onboardingFlowVariant).toBe('legacy')
        })

        it('maps the original control flag value to legacy', () => {
            setVariant('control')
            expect(logic.values.onboardingFlowVariant).toBe('legacy')
        })

        it('returns self-driving when the flag selects it', () => {
            setVariant('self-driving')
            expect(logic.values.onboardingFlowVariant).toBe('self-driving')
        })

        it('falls back to legacy for an unregistered variant', () => {
            setVariant('some_future_variant')
            expect(logic.values.onboardingFlowVariant).toBe('legacy')
        })
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
