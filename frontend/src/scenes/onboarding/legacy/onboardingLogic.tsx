import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { type SetupTaskId } from 'lib/components/ProductSetup'
import { globalSetupLogic } from 'lib/components/ProductSetup/globalSetupLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { isKeyOf } from 'lib/utils/guards'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { billingLogic } from 'scenes/billing/billingLogic'
import { resolveOnboardingFlowVariant } from 'scenes/onboarding/onboardingVariants'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation/sidepanel/sidePanelStateLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { Breadcrumb, OnboardingProduct, OnboardingStepKey } from '~/types'

import { arraysEqual, parseProductsParam, stepKeyToTitle } from './onboardingFlowUtils'
import type { onboardingLogicType } from './onboardingLogicType'
import { appendSharedTrailingSteps } from './sharedSteps'
import { onboardingProviderRegistry } from './stepProviderRegistry'
import { type OnboardingFlowContext, type OnboardingStepDescriptor } from './types'

/** Interface kept for callers that import it (legacy step components). */
export interface OnboardingStepComponentType<P = object> extends React.FC<P> {
    stepKey: OnboardingStepKey
}

export interface OnboardingLogicProps {
    onCompleteOnboarding?: (key: ProductKey) => void
}

export const onboardingLogic = kea<onboardingLogicType>([
    props({} as OnboardingLogicProps),
    path(['scenes', 'onboarding', 'onboardingLogic']),
    connect(() => ({
        values: [
            billingLogic,
            ['billing'],
            teamLogic,
            ['currentTeam'],
            userLogic,
            ['user'],
            preflightLogic,
            ['isCloudOrDev', 'preflight'],
            organizationLogic,
            ['currentOrganization'],
            sidePanelStateLogic,
            ['modalMode'],
            featureFlagLogic,
            ['featureFlags', 'receivedFeatureFlags'],
        ],
        actions: [
            billingLogic,
            ['loadBillingSuccess'],
            teamLogic,
            ['updateCurrentTeam', 'updateCurrentTeamSuccess', 'recordProductIntentOnboardingComplete'],
            sidePanelStateLogic,
            ['openSidePanel'],
            globalSetupLogic,
            ['openGlobalSetup'],
        ],
    })),
    actions({
        setProduct: (product: OnboardingProduct | null) => ({ product }),
        setProductKey: (productKey: ProductKey | null) => ({ productKey }),
        setSecondaryProductKeys: (keys: ProductKey[]) => ({ keys }),
        setStepId: (stepId: string) => ({ stepId }),
        markStepsVisited: (stepIds: string[]) => ({ stepIds }),
        resetOnboardingFlowState: true,
        completeOnboarding: (options?: { redirectUrlOverride?: string }) => ({
            redirectUrlOverride: options?.redirectUrlOverride,
        }),
        setSubscribedDuringOnboarding: (subscribedDuringOnboarding: boolean) => ({ subscribedDuringOnboarding }),
        setTeamPropertiesForProduct: (productKey: ProductKey) => ({ productKey }),
        setWaitForBilling: (waitForBilling: boolean) => ({ waitForBilling }),
        goToNextStep: true,
        goToPreviousStep: true,
        setOnCompleteOnboardingRedirectUrl: (url: string | null) => ({ url }),
        skipOnboarding: true,
        // Distinct from `setProductKey(null)`: navigating to `/onboarding` (the product
        // selection page) should not trigger the invalid-key redirect-to-home path.
        clearProductKey: true,
        setIsCompleting: (isCompleting: boolean) => ({ isCompleting }),
    }),
    reducers(() => ({
        // True between dispatching `completeOnboarding` and the resulting team PATCH
        // settling. Guards against double-fires from button double-clicks, re-renders,
        // and the post-billing `?success=true` round-trip.
        isCompleting: [
            false,
            {
                setIsCompleting: (_, { isCompleting }) => isCompleting,
                resetOnboardingFlowState: () => false,
            },
        ],
        productKey: [
            null as ProductKey | null,
            {
                setProductKey: (_, { productKey }) => productKey,
                clearProductKey: () => null,
            },
        ],
        product: [
            null as OnboardingProduct | null,
            {
                setProduct: (_, { product }) => product ?? null,
            },
        ],
        secondaryProductKeys: [
            [] as ProductKey[],
            {
                setSecondaryProductKeys: (_, { keys }) => keys,
                resetOnboardingFlowState: () => [],
            },
        ],
        stepId: [
            '' as string,
            {
                setStepId: (_, { stepId }) => stepId,
                resetOnboardingFlowState: () => '',
            },
        ],
        // Tracks which step ids the user has actually visited during this onboarding session.
        // Used to (a) tick `setupTaskId`s for steps the user reached even when they skipped
        // ahead via a breadcrumb, and (b) only mark a product as completed when the user
        // actually saw at least one of its steps.
        visitedStepIds: [
            [] as string[],
            {
                markStepsVisited: (state, { stepIds }) => {
                    const next = new Set(state)
                    stepIds.forEach((id) => next.add(id))
                    return Array.from(next)
                },
                resetOnboardingFlowState: () => [],
            },
        ],
        subscribedDuringOnboarding: [
            false,
            {
                setSubscribedDuringOnboarding: (_, { subscribedDuringOnboarding }) => subscribedDuringOnboarding,
                resetOnboardingFlowState: () => false,
            },
        ],
        waitForBilling: [
            false,
            {
                setWaitForBilling: (_, { waitForBilling }) => waitForBilling,
                resetOnboardingFlowState: () => false,
            },
        ],
        onCompleteOnboardingRedirectUrlOverride: [
            null as string | null,
            {
                setOnCompleteOnboardingRedirectUrl: (_, { url }) => url,
                resetOnboardingFlowState: () => null,
            },
        ],
    })),
    selectors({
        onboardingFlowVariant: [
            (s) => [s.featureFlags],
            (featureFlags): string => resolveOnboardingFlowVariant(featureFlags),
        ],
        canInviteTeammates: [
            (s) => [s.currentOrganization, s.user],
            (currentOrganization, user): boolean => {
                if (currentOrganization?.members_can_invite) {
                    return true
                }
                const level = user?.organization?.membership_level
                return typeof level === 'number' && level >= OrganizationMembershipLevel.Admin
            },
        ],
        billingProduct: [
            (s) => [s.billing, s.productKey],
            (billing, productKey) => billing?.products?.find((p) => p.type === productKey) ?? null,
        ],
        shouldShowBillingStep: [
            (s) => [s.subscribedDuringOnboarding, s.isCloudOrDev, s.billing, s.billingProduct, s.stepId],
            (subscribedDuringOnboarding, isCloudOrDev, billing, billingProduct, stepId): boolean => {
                if (!isCloudOrDev || !billing?.products || !billingProduct) {
                    return false
                }
                // Keep the plans step in the flow whenever the URL explicitly targets it — otherwise an
                // already-subscribed user landing here (e.g. after a trial cancel reloads without
                // `?success=true`) would drop the step from the flow and get stuck on a spinner.
                const onPlansStep =
                    stepId === OnboardingStepKey.PLANS || stepId.startsWith(`${OnboardingStepKey.PLANS}:`)
                return !billingProduct?.subscribed || subscribedDuringOnboarding || onPlansStep
            },
        ],
        flow: [
            // Note: depend on `currentTeam` directly (rather than projecting a slim shape)
            // because providers read varied fields and a kea-style shallow projection still
            // re-fires on object identity. The cost is small: descriptor allocation is
            // microseconds and React's reconciler keeps the rendered subtree stable as
            // long as `currentFlowStep.id` is unchanged.
            (s) => [
                s.productKey,
                s.secondaryProductKeys,
                s.currentTeam,
                s.billing,
                s.billingProduct,
                s.shouldShowBillingStep,
                s.isCloudOrDev,
                s.subscribedDuringOnboarding,
                s.canInviteTeammates,
            ],
            (
                primary,
                secondaries,
                currentTeam,
                billing,
                billingProduct,
                shouldShowBilling,
                isCloudOrDev,
                subscribedDuringOnboarding,
                canInviteTeammates
            ): OnboardingStepDescriptor[] => {
                if (!primary) {
                    return []
                }
                const orderedProducts: ProductKey[] = [primary, ...secondaries]
                const baseCtx: Omit<OnboardingFlowContext, 'role'> = {
                    primary,
                    secondaries,
                    currentTeam,
                    billing,
                    isCloudOrDev: Boolean(isCloudOrDev),
                    subscribedDuringOnboarding,
                    canInviteTeammates,
                }
                const productSteps = orderedProducts.flatMap((p, i) => {
                    const provider = onboardingProviderRegistry[p]
                    if (!provider) {
                        return []
                    }
                    return provider.steps({ ...baseCtx, role: i === 0 ? 'primary' : 'secondary' })
                })
                const allSteps = appendSharedTrailingSteps(
                    productSteps,
                    { ...baseCtx, role: 'primary' },
                    billingProduct,
                    shouldShowBilling
                )
                // Collapse functionally-identical steps (e.g. multiple posthog-js install
                // steps when the user picks several products that share the SDK). First
                // occurrence wins so the primary product's install step — which carries
                // the most configuration — survives. When a descriptor is dropped, we
                // accumulate its `setupTaskId` and `productKey` for the survivor so:
                //   (1) advancing past the kept step still ticks every dropped product's
                //       setup-checklist task, and
                //   (2) `completeOnboarding` can credit the dropped products' visit even
                //       though no surviving descriptor carries their productKey.
                // Two-pass build: first accumulate into per-survivor scratch records, then
                // emit fully-frozen descriptors. Avoids mutating descriptors after they've
                // been pushed to the result array (selector purity).
                interface AccumulatedExtras {
                    setupTaskIds: SetupTaskId[]
                    productKeys: ProductKey[]
                }
                const extras = new Map<string, AccumulatedExtras>()
                for (const step of allSteps) {
                    if (!step.dedupKey) {
                        continue
                    }
                    let entry = extras.get(step.dedupKey)
                    if (!entry) {
                        entry = { setupTaskIds: [], productKeys: [step.productKey] }
                        extras.set(step.dedupKey, entry)
                        continue
                    }
                    if (step.setupTaskId && !entry.setupTaskIds.includes(step.setupTaskId)) {
                        entry.setupTaskIds.push(step.setupTaskId)
                    }
                    if (!entry.productKeys.includes(step.productKey)) {
                        entry.productKeys.push(step.productKey)
                    }
                }
                const emittedDedup = new Set<string>()
                const result: OnboardingStepDescriptor[] = []
                for (const step of allSteps) {
                    if (!step.dedupKey) {
                        result.push(step)
                        continue
                    }
                    if (emittedDedup.has(step.dedupKey)) {
                        continue
                    }
                    emittedDedup.add(step.dedupKey)
                    const entry = extras.get(step.dedupKey)
                    if (!entry || (entry.setupTaskIds.length === 0 && entry.productKeys.length <= 1)) {
                        result.push(step)
                        continue
                    }
                    result.push(
                        Object.freeze({
                            ...step,
                            additionalSetupTaskIds: entry.setupTaskIds.slice(),
                            additionalProductKeys: entry.productKeys.slice(),
                        })
                    )
                }
                // Reorder: all install steps to the front, with the primary product's
                // install first among them — so the "Start with" choice (which product is
                // primary) decides which SDK instructions the user sees first. Stable sort
                // preserves each provider's intra-group order — non-install steps (configure,
                // link_data, plans, invite) keep their relative positions, just appear
                // after the installs. Buckets:
                //   0 — Install for the primary product (the SDK the user chose to start with)
                //   1 — Install for any secondary product (Logs/OTel, Workflows, etc.)
                //   2 — everything else (configure, plans, invite, link_data, …)
                const sortBucket = (step: OnboardingStepDescriptor): number => {
                    if (step.stepKey !== OnboardingStepKey.INSTALL) {
                        return 2
                    }
                    return step.role === 'primary' ? 0 : 1
                }
                return result.slice().sort((a, b) => sortBucket(a) - sortBucket(b))
            },
        ],
        onboardingStepKeys: [
            (s) => [s.flow],
            (flow: OnboardingStepDescriptor[]): OnboardingStepKey[] => flow.map((step) => step.stepKey),
        ],
        currentFlowStep: [
            (s) => [s.flow, s.stepId],
            (flow: OnboardingStepDescriptor[], stepId): OnboardingStepDescriptor | null => {
                if (!flow.length) {
                    // If the user explicitly asked for a step (URL has `?step=...`) but the
                    // flow hasn't been built yet (billing/team still loading), we MUST NOT
                    // fall through to `flow[0]` — that would render a different product's
                    // step than the URL indicates and fire analytics for the wrong step.
                    // Returning null lets `OnboardingFlowHost` show a spinner until the
                    // flow rebuilds and the requested step resolves.
                    return null
                }
                if (!stepId) {
                    return flow[0]
                }
                const exact = flow.find((step) => step.id === stepId)
                if (exact) {
                    return exact
                }
                // Backwards-compat: bare step keys (no namespace) resolve to the first
                // matching descriptor — covers older bookmarks and inbound links from
                // setup-task `getUrl` callsites that pre-date the namespaced ids.
                const looseMatch = flow.find((step) => step.stepKey === stepId)
                if (looseMatch) {
                    return looseMatch
                }
                // Bad step id — neither exact nor loose match. Return null so
                // `OnboardingFlowHost` shows a loading state instead of silently
                // rendering `flow[0]` while the URL keeps a stale stepId. The
                // urlToAction handler reconciles this by calling `setStepId('')`
                // when the parsed stepValue can't be resolved.
                return null
            },
        ],
        flowIndex: [
            (s) => [s.flow, s.currentFlowStep],
            (flow, currentFlowStep): number =>
                currentFlowStep ? flow.findIndex((step) => step.id === currentFlowStep.id) : -1,
        ],
        currentStepKey: [
            (s) => [s.currentFlowStep],
            (currentFlowStep): OnboardingStepKey | null => currentFlowStep?.stepKey ?? null,
        ],
        currentStepProductKey: [
            (s) => [s.currentFlowStep, s.productKey],
            (currentFlowStep, productKey): ProductKey | null => currentFlowStep?.productKey ?? productKey,
        ],
        totalOnboardingSteps: [(s) => [s.flow], (flow) => flow.length],
        hasNextStep: [
            (s) => [s.flow, s.flowIndex],
            (flow, flowIndex): boolean => flowIndex >= 0 && flowIndex < flow.length - 1,
        ],
        hasPreviousStep: [(s) => [s.flowIndex], (flowIndex): boolean => flowIndex > 0],
        breadcrumbs: [
            (s) => [s.productKey, s.currentFlowStep, s.secondaryProductKeys],
            (productKey, currentFlowStep, secondaryProductKeys): Breadcrumb[] => {
                const stepName = stepKeyToTitle(currentFlowStep?.stepKey ?? undefined)
                return [
                    {
                        key: Scene.Onboarding,
                        name:
                            availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]
                                ?.breadcrumbsName ??
                            availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.name,
                        path: availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.url,
                        iconType: 'action',
                    },
                    {
                        key: availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]?.scene,
                        name: stepName,
                        // Preserve `withProducts` and use the namespaced step id so the URL
                        // round-trips through `urlToAction` without collapsing the flow's
                        // secondary products or losing the active step's product attribution.
                        path: urls.onboarding({
                            productKey: productKey ?? undefined,
                            step: currentFlowStep?.id,
                            withProducts: secondaryProductKeys.length ? secondaryProductKeys : undefined,
                        }),
                        iconType: 'action',
                    },
                ]
            },
        ],
        onCompleteOnboardingRedirectUrl: [
            (s) => [s.productKey, s.onCompleteOnboardingRedirectUrlOverride],
            (productKey: ProductKey | null, onCompleteOnboardingRedirectUrlOverride: string | null): string => {
                if (onCompleteOnboardingRedirectUrlOverride) {
                    return onCompleteOnboardingRedirectUrlOverride
                }
                if (!productKey) {
                    return urls.default()
                }
                return onboardingProviderRegistry[productKey]?.completeRedirectUrl?.() ?? urls.default()
            },
        ],
    }),
    listeners(({ actions, values, props, selectors }) => ({
        setProduct: ({ product }) => {
            if (!product) {
                window.location.href = urls.default()
            }
        },
        setTeamPropertiesForProduct: ({ productKey }) => {
            switch (productKey) {
                case ProductKey.PRODUCT_ANALYTICS:
                    return
                case ProductKey.SESSION_REPLAY:
                    teamLogic.actions.updateCurrentTeam({
                        session_recording_opt_in: true,
                        capture_console_log_opt_in: true,
                        capture_performance_opt_in: true,
                    })
                    return
                case ProductKey.FEATURE_FLAGS:
                    return
                case ProductKey.AI_OBSERVABILITY:
                    return
                default:
                    return
            }
        },
        setProductKey: ({ productKey }, _, __, previousState) => {
            if (!productKey || !isKeyOf(productKey, availableOnboardingProducts)) {
                window.location.href = urls.default()
                return
            }
            // Reset per-flow state when transitioning into a new product. Without this,
            // a redirect override / `subscribedDuringOnboarding` / `waitForBilling` set
            // during a previous onboarding in the same SPA tab would carry over and
            // hijack the new flow's behaviour.
            const previousKey = selectors.productKey(previousState)
            if (previousKey && previousKey !== productKey) {
                actions.resetOnboardingFlowState()
            }
            actions.setProduct(availableOnboardingProducts[productKey])
        },
        setSubscribedDuringOnboarding: ({ subscribedDuringOnboarding }) => {
            if (!subscribedDuringOnboarding) {
                return
            }
            // Strip /project/<id>/ prefix before splitting, otherwise the path index
            // points at the project id instead of the product key.
            const fallbackKey = removeProjectIdIfPresent(window.location.pathname).split('/')[2] as
                | ProductKey
                | undefined
            const productKey = values.productKey || fallbackKey
            // Don't fire the analytics event without a valid productKey — would record
            // `productKey: undefined` rows which dirty downstream dashboards.
            if (!productKey || !isKeyOf(productKey, availableOnboardingProducts)) {
                return
            }
            eventUsageLogic.actions.reportSubscribedDuringOnboarding(productKey)
        },
        completeOnboarding: ({ redirectUrlOverride }) => {
            // Idempotency guard. Without this, a double-click on Finish, a re-render
            // calling advance() twice, or back-then-forward into the last step plus
            // pressing Finish again all fire duplicate product-intent writes,
            // analytics events, and team PATCHes.
            if (values.isCompleting) {
                return
            }
            const primary = values.productKey
            if (!primary) {
                return
            }
            actions.setIsCompleting(true)
            if (redirectUrlOverride) {
                actions.setOnCompleteOnboardingRedirectUrl(redirectUrlOverride)
            }
            // Analytics: keep the existing single event for the primary product to avoid
            // changing dashboards. Secondary products are still recorded via
            // `recordProductIntentOnboardingComplete` and `has_completed_onboarding_for`,
            // but don't fire an additional `onboarding completed` analytics event.
            eventUsageLogic.actions.reportOnboardingCompleted(primary)
            props.onCompleteOnboarding?.(primary)
            // Error Tracking has a side-effect tied to onboarding completion (set up in the
            // legacy view): turn on autocapture_exceptions_opt_in. Preserved here.
            if (primary === ProductKey.ERROR_TRACKING) {
                teamLogic.actions.updateCurrentTeam({ autocapture_exceptions_opt_in: true })
            }
            // Only mark a product as fully onboarded when the user actually visited at
            // least one of its steps. Without this guard, a hand-crafted URL with an
            // arbitrary `?with=...` list would silently flip every secondary's flag on
            // the first "Continue" — even ones the user never saw.
            //
            // Two extra signals beyond `visitedStepIds`:
            //   - The user is, by definition, looking at the current step right now.
            //     Include `currentFlowStep` even if `setStepId` never fired for it
            //     (deep-link entry, or final step reached by goToNextStep).
            //   - Walk every step from the start of the flow up to the current step:
            //     a deep link past the start of a multi-product flow implies the user
            //     committed to seeing the preceding steps' products.
            //   - For each visited step, also credit `additionalProductKeys` from the
            //     dedup pass so collapsed-into-survivor secondaries get marked.
            const visited = new Set(values.visitedStepIds)
            const currentStep = values.currentFlowStep
            if (currentStep) {
                visited.add(currentStep.id)
            }
            const currentIndex = values.flowIndex
            if (currentIndex >= 0) {
                for (let i = 0; i <= currentIndex; i++) {
                    visited.add(values.flow[i].id)
                }
            }
            const visitedProducts = new Set<ProductKey>([primary])
            // Tick every reached step's setupTaskId — including the final step's, which
            // would otherwise never fire because `setStepId` doesn't tick the destination.
            const setup = globalSetupLogic.findMounted()
            const tickedTaskIds = new Set<SetupTaskId>()
            for (const step of values.flow) {
                if (!visited.has(step.id)) {
                    continue
                }
                visitedProducts.add(step.productKey)
                for (const productKey of step.additionalProductKeys ?? []) {
                    visitedProducts.add(productKey)
                }
                if (step.setupTaskId) {
                    tickedTaskIds.add(step.setupTaskId)
                }
                for (const id of step.additionalSetupTaskIds ?? []) {
                    tickedTaskIds.add(id)
                }
            }
            if (setup && tickedTaskIds.size > 0) {
                setup.actions.markTaskAsCompleted(Array.from(tickedTaskIds))
            }
            for (const productKey of visitedProducts) {
                actions.recordProductIntentOnboardingComplete({ product_type: productKey as ProductKey })
            }
            const completedMap: Record<string, boolean> = { ...values.currentTeam?.has_completed_onboarding_for }
            for (const productKey of visitedProducts) {
                completedMap[productKey] = true
            }
            teamLogic.actions.updateCurrentTeam({ has_completed_onboarding_for: completedMap })
        },
        skipOnboarding: () => {
            // Quick Start does not auto-open here. The button remains in the scene title
            // bar so users can open it manually. Auto-opening it conflicted with the welcome
            // dialog mounted in GlobalModals for invitees (delegates and ordinary members),
            // creating two competing "what to do next" surfaces.
            router.actions.push(values.onCompleteOnboardingRedirectUrl)
        },
        updateCurrentTeamSuccess: (val) => {
            const isCompletionPatch =
                values.productKey && val.payload?.has_completed_onboarding_for?.[values.productKey]
            if (!isCompletionPatch) {
                return
            }
            actions.setIsCompleting(false)
        },
        updateCurrentTeamFailure: (val) => {
            // Same scoping as the success listener: only react to the completion PATCH,
            // not to unrelated team updates that happen to fail while the user is on
            // the last step.
            const isCompletionPatch =
                values.productKey && val.payload?.has_completed_onboarding_for?.[values.productKey]
            if (!isCompletionPatch) {
                return
            }
            actions.setIsCompleting(false)
        },
        setStepId: ({ stepId }, _, __, previousState) => {
            // kea listeners receive (payload, breakpoint, action, previousState). We need
            // the 4th arg here, not the 2nd — that was the breakpoint function.
            const previousStepId = selectors.stepId(previousState)

            // URL self-correction: if the user navigated to a stepId we can't resolve
            // (typo'd bookmark, deprecated step name, secondary product not in `?with=`),
            // `currentFlowStep` returns null and the host shows a spinner forever.
            // Reconcile by falling through to flow[0].
            //
            // Important: only self-correct when the stepId is genuinely unknown — NOT when
            // it's a valid OnboardingStepKey that simply hasn't been emitted into the flow
            // yet. Steps like `plans` are appended async (after billing loads) by
            // `appendSharedTrailingSteps`; self-correcting too eagerly here would clobber
            // the URL before the flow settles, leaving the user on `flow[0]` even after
            // billing arrives.
            const isKnownStepKey = (id: string): boolean =>
                Object.values(OnboardingStepKey).includes(id as OnboardingStepKey) || id.includes(':')
            if (stepId && values.flow.length > 0 && !isKnownStepKey(stepId)) {
                const exact = values.flow.find((step) => step.id === stepId)
                const loose = exact ? null : values.flow.find((step) => step.stepKey === stepId)
                if (!exact && !loose) {
                    actions.setStepId('')
                    return
                }
            }

            if (!previousStepId || previousStepId === stepId) {
                if (stepId) {
                    actions.markStepsVisited([stepId])
                }
                return
            }

            const flow = values.flow
            const previousIndex = flow.findIndex((step) => step.id === previousStepId)
            const nextIndex = flow.findIndex((step) => step.id === stepId)

            // Mark every step from previous → next as visited (forward jumps via
            // breadcrumb included). Backward jumps don't add new visits — already-marked
            // steps stay marked thanks to the Set semantics in the reducer.
            if (previousIndex >= 0 && nextIndex > previousIndex) {
                const traversed = flow.slice(previousIndex, nextIndex + 1).map((step) => step.id)
                actions.markStepsVisited(traversed)
                // Tick setupTaskId for every step the user traversed away from, plus
                // any additionalSetupTaskIds inherited from descriptors that were
                // collapsed via the dedup pass. Single batched call — looping per id
                // would have each call read the same stale `currentTeam.onboarding_tasks`
                // snapshot and clobber prior writes (only the last id would survive).
                const setup = globalSetupLogic.findMounted()
                if (setup) {
                    const ticked = new Set<SetupTaskId>()
                    for (const step of flow.slice(previousIndex, nextIndex)) {
                        if (step.setupTaskId) {
                            ticked.add(step.setupTaskId)
                        }
                        for (const id of step.additionalSetupTaskIds ?? []) {
                            ticked.add(id)
                        }
                    }
                    if (ticked.size > 0) {
                        setup.actions.markTaskAsCompleted(Array.from(ticked))
                    }
                }
            } else if (stepId) {
                // Backward / lateral / outside-flow movement: still record the new step as visited.
                actions.markStepsVisited([stepId])
            }
        },
        goToNextStep: () => {
            // Empty / not-yet-built flow: do nothing. Without this guard, a misconfigured
            // product (registered in availableOnboardingProducts but not in
            // stepProviderRegistry) would cascade through completeOnboarding the first
            // time anything triggered goToNextStep.
            if (!values.flow.length) {
                return
            }
            const next = values.flow[values.flowIndex + 1]
            if (next) {
                actions.setStepId(next.id)
                return
            }
            actions.completeOnboarding()
        },
        goToPreviousStep: () => {
            const prev = values.flow[values.flowIndex - 1]
            if (prev) {
                actions.setStepId(prev.id)
            }
        },
    })),
    actionToUrl(({ values, actions }) => ({
        setStepId: ({ stepId }) => {
            // `success`/`upgraded` are billing-callback signals consumed once; keeping them in
            // the URL re-fires the `subscribed during onboarding` event on every step nav.
            const existingParams = router.values.searchParams ?? {}
            const {
                step: _step,
                with: _with,
                productKey: _productKey,
                success: _success,
                upgraded: _upgraded,
                ...passthrough
            } = existingParams
            void _step
            void _with
            void _productKey
            void _success
            void _upgraded
            // Drop the stepId from the URL if it's not resolvable in the current flow.
            // Without this, the self-correcting `setStepId('')` from the listener races
            // with the OUTER `actionToUrl` for the bogus stepId — kea fires the outer
            // actionToUrl AFTER the listener completes, which re-pushes the bogus URL
            // through urlToAction and re-dispatches setStepId(bogus), looping
            // indefinitely. Stripping unresolvable stepIds here keeps the URL
            // self-consistent with the reducer state.
            // Mirror the `setStepId` listener's `isKnownStepKey` heuristic. Billing-gated
            // steps (plans, invite_teammates, link_data) are appended async after billing
            // loads, so they may not be in `flow` when the URL push lands. Stripping them
            // from the URL would re-fire `setStepId('')` and permanently lose the request.
            const isKnownStepKey =
                Object.values(OnboardingStepKey).includes(stepId as OnboardingStepKey) || stepId.includes(':')
            const stepResolves =
                !stepId ||
                values.flow.length === 0 ||
                isKnownStepKey ||
                !!values.flow.find((s) => s.id === stepId || s.stepKey === stepId)
            const url = urls.onboarding({
                productKey: values.productKey ?? undefined,
                step: stepResolves ? stepId || undefined : undefined,
                withProducts: values.secondaryProductKeys.length ? values.secondaryProductKeys : undefined,
            })
            // Use `replace` so the user doesn't accumulate one history entry per onboarding
            // step — otherwise pressing browser Back after onboarding requires N presses to
            // escape, where N is the number of steps the user advanced.
            return [url, passthrough, undefined, { replace: true }]
        },
        updateCurrentTeamSuccess(val) {
            if (values.productKey && val.payload?.has_completed_onboarding_for?.[values.productKey]) {
                const redirectUrl = values.onCompleteOnboardingRedirectUrl
                // Reset the override after consuming it so a subsequent onboarding session
                // in the same tab doesn't reuse a stale redirect target.
                if (values.onCompleteOnboardingRedirectUrlOverride) {
                    actions.setOnCompleteOnboardingRedirectUrl(null)
                }
                return [redirectUrl]
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/onboarding/:productKey': ({ productKey }, params: Record<string, unknown>) => {
            if (!productKey || !Object.hasOwn(availableOnboardingProducts, productKey)) {
                return
            }

            const success = params.success
            const upgraded = params.upgraded
            const step = params.step
            const withRaw = params.with

            // Order matters: `setProductKey` may dispatch `resetOnboardingFlowState`
            // (which resets `subscribedDuringOnboarding` to false) when transitioning
            // between products. Set the product first, THEN apply the post-payment
            // subscription flag, so the reset doesn't clobber it.
            if (productKey !== values.productKey) {
                actions.setProductKey(productKey as ProductKey)
            }

            if (success || upgraded) {
                actions.setSubscribedDuringOnboarding(true)
            }

            const parsedSecondaries = parseProductsParam(withRaw).filter((k) => k !== productKey)
            // Skip the dispatch when nothing changed — kea reducers compare by reference,
            // so re-emitting an identical-but-fresh array still triggers downstream
            // selector recomputes (notably `flow`, which is the most expensive selector
            // in this logic).
            if (!arraysEqual(parsedSecondaries, values.secondaryProductKeys)) {
                actions.setSecondaryProductKeys(parsedSecondaries)
            }

            const stepValue = typeof step === 'string' ? step : ''
            // Wait-for-billing gating: same intent as before, just keyed off the step value
            // (namespaced or bare). Plans-step bookmarks should not advance until billing
            // has loaded so the upgrade UI has data to render.
            const isPlansStep =
                stepValue === OnboardingStepKey.PLANS || stepValue.startsWith(`${OnboardingStepKey.PLANS}:`)
            if (isPlansStep) {
                actions.setWaitForBilling(true)
            }

            if (stepValue !== values.stepId) {
                actions.setStepId(stepValue)
            }
        },
        '/onboarding': () => {
            // Land on the product-selection page. We can't dispatch `setProductKey(null)`
            // because that listener treats null as "invalid product" and hard-redirects
            // to the home page — preventing users from returning here from inside an
            // existing flow.
            if (values.productKey !== null) {
                actions.clearProductKey()
            }
            actions.resetOnboardingFlowState()
        },
    })),
])
