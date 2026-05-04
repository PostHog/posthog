import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { type SetupTaskId } from 'lib/components/ProductSetup'
import { globalSetupLogic } from 'lib/components/ProductSetup/globalSetupLogic'
import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isKeyOf } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { ProductKey } from '~/queries/schema/schema-general'
import { Breadcrumb, OnboardingProduct, OnboardingStepKey } from '~/types'

import type { onboardingLogicType } from './onboardingLogicType'
import { postOnboardingModalLogic } from './postOnboardingModalLogic'
import { appendSharedTrailingSteps } from './sharedSteps'
import { stepProviderRegistry } from './stepProviderRegistry'
import { type OnboardingFlowContext, type OnboardingStepDescriptor } from './types'
import { availableOnboardingProducts } from './utils'

/** Interface kept for callers that import it (legacy step components). */
export interface OnboardingStepComponentType<P = object> extends React.FC<P> {
    stepKey: OnboardingStepKey
}

export interface OnboardingLogicProps {
    onCompleteOnboarding?: (key: ProductKey) => void
}

const STEP_KEY_TITLE_OVERRIDES: Partial<Record<OnboardingStepKey, string>> = {
    [OnboardingStepKey.LINK_DATA]: 'Import data',
}

export const stepKeyToTitle = (stepKey?: OnboardingStepKey): undefined | string => {
    if (!stepKey) {
        return undefined
    }
    if (STEP_KEY_TITLE_OVERRIDES[stepKey]) {
        return STEP_KEY_TITLE_OVERRIDES[stepKey]
    }
    return stepKey
        .split('_')
        .map((part, i) => (i == 0 ? part[0].toUpperCase() + part.substring(1) : part))
        .join(' ')
}

export const getOnboardingCompleteRedirectUri = (productKey: ProductKey): string => {
    switch (productKey) {
        case ProductKey.PRODUCT_ANALYTICS:
            return urls.insightQuickStart()
        case ProductKey.WEB_ANALYTICS:
            return urls.webAnalytics()
        case ProductKey.SESSION_REPLAY:
            return urls.replay()
        case ProductKey.FEATURE_FLAGS:
            return urls.featureFlags()
        case ProductKey.SURVEYS:
            return urls.surveyWizard()
        case ProductKey.ERROR_TRACKING:
            return urls.errorTracking()
        case ProductKey.LLM_ANALYTICS:
            return urls.llmAnalyticsDashboard()
        case ProductKey.WORKFLOWS:
            return urls.workflows()
        case ProductKey.LOGS:
            return urls.logs()
        default:
            return urls.default()
    }
}

const MAX_WITH_PRODUCTS = 16

const parseProductsParam = (raw: unknown): ProductKey[] => {
    const value = typeof raw === 'string' ? raw : ''
    if (!value) {
        return []
    }
    // Dedupe BEFORE truncation so a malicious or buggy producer can't push valid keys
    // out of the resulting array by stuffing the head with duplicates.
    const unique = Array.from(new Set(value.split(',')))
    return unique
        .filter((k: string) => Object.hasOwn(availableOnboardingProducts, k))
        .slice(0, MAX_WITH_PRODUCTS) as ProductKey[]
}

const arraysEqual = <T,>(a: readonly T[], b: readonly T[]): boolean => {
    if (a.length !== b.length) {
        return false
    }
    for (let i = 0; i < a.length; i++) {
        if (a[i] !== b[i]) {
            return false
        }
    }
    return true
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
            postOnboardingModalLogic,
            ['modalShown'],
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
            postOnboardingModalLogic,
            ['openPostOnboardingModal'],
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
        setAwaitingPostOnboardingModal: (awaiting: boolean) => ({ awaiting }),
    }),
    reducers(() => ({
        isAwaitingPostOnboardingModal: [
            false,
            {
                setAwaitingPostOnboardingModal: (_, { awaiting }) => awaiting,
                resetOnboardingFlowState: () => false,
            },
        ],
        productKey: [
            null as ProductKey | null,
            {
                setProductKey: (_, { productKey }) => productKey,
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
            (s) => [s.product, s.subscribedDuringOnboarding, s.isCloudOrDev, s.billing, s.billingProduct],
            (_product, subscribedDuringOnboarding, isCloudOrDev, billing, billingProduct): boolean => {
                if (!isCloudOrDev || !billing?.products || !billingProduct) {
                    return false
                }
                return !billingProduct?.subscribed || subscribedDuringOnboarding
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
                    const provider = stepProviderRegistry[p]
                    if (!provider) {
                        return []
                    }
                    return provider({ ...baseCtx, role: i === 0 ? 'primary' : 'secondary' })
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
                // the most configuration — survives. When a descriptor is dropped, its
                // `setupTaskId` is merged into the survivor's `additionalSetupTaskIds`
                // so advancing past the kept step still ticks every dropped product's
                // setup-checklist task. Steps without a dedupKey pass through unchanged.
                const survivors = new Map<string, OnboardingStepDescriptor>()
                const result: OnboardingStepDescriptor[] = []
                for (const step of allSteps) {
                    if (!step.dedupKey) {
                        result.push(step)
                        continue
                    }
                    const existing = survivors.get(step.dedupKey)
                    if (!existing) {
                        // First occurrence — keep, and start a fresh additionalSetupTaskIds
                        // array so we don't mutate the descriptor returned by the provider.
                        const cloned: OnboardingStepDescriptor = { ...step, additionalSetupTaskIds: [] }
                        survivors.set(step.dedupKey, cloned)
                        result.push(cloned)
                        continue
                    }
                    // Drop this step — but carry its setupTaskId forward.
                    if (step.setupTaskId && !existing.additionalSetupTaskIds?.includes(step.setupTaskId)) {
                        existing.additionalSetupTaskIds = [...(existing.additionalSetupTaskIds ?? []), step.setupTaskId]
                    }
                }
                return result
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
                if (stepId) {
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
                    // Bad step id — neither exact nor loose match. Prefer the first step
                    // over silently masking the mismatch; the listener for setStepId will
                    // self-correct the URL.
                }
                return flow[0]
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
            (productKey, onCompleteOnboardingRedirectUrlOverride): string => {
                if (onCompleteOnboardingRedirectUrlOverride) {
                    return onCompleteOnboardingRedirectUrlOverride
                }
                return productKey ? getOnboardingCompleteRedirectUri(productKey) : urls.default()
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
                case ProductKey.LLM_ANALYTICS:
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
            if (subscribedDuringOnboarding) {
                // Strip /project/<id>/ prefix before splitting, otherwise the path index
                // points at the project id instead of the product key.
                const fallbackKey = removeProjectIdIfPresent(window.location.pathname).split('/')[2] as ProductKey
                const productKey = values.productKey || fallbackKey
                eventUsageLogic.actions.reportSubscribedDuringOnboarding(productKey)
            }
        },
        completeOnboarding: ({ redirectUrlOverride }) => {
            if (redirectUrlOverride) {
                actions.setOnCompleteOnboardingRedirectUrl(redirectUrlOverride)
            }
            const primary = values.productKey
            if (!primary) {
                return
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
            const visited = new Set(values.visitedStepIds)
            const visitedProducts = new Set<ProductKey>([primary])
            for (const step of values.flow) {
                if (visited.has(step.id) && step.role !== undefined) {
                    visitedProducts.add(step.productKey)
                }
            }
            for (const productKey of visitedProducts) {
                actions.recordProductIntentOnboardingComplete({ product_type: productKey as ProductKey })
            }
            actions.setAwaitingPostOnboardingModal(true)
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
        updateCurrentTeamSuccess: () => {
            if (values.isAwaitingPostOnboardingModal && values.productKey) {
                actions.setAwaitingPostOnboardingModal(false)
                const isVariant =
                    values.receivedFeatureFlags &&
                    values.featureFlags[FEATURE_FLAGS.POST_ONBOARDING_MODAL_EXPERIMENT] === 'test'

                if (isVariant && !values.modalShown) {
                    actions.openPostOnboardingModal(values.productKey)
                }
            }
        },
        updateCurrentTeamFailure: () => {
            // Mirror behaviour change in completeOnboarding: if the team patch fails, drop
            // the awaiting flag and surface the failure to the user. Without this the
            // Finish button silently no-ops and the user is stranded on the last step.
            if (values.isAwaitingPostOnboardingModal) {
                actions.setAwaitingPostOnboardingModal(false)
                lemonToast.error(
                    "We couldn't finish onboarding. Please try again or contact support if the problem persists."
                )
            }
        },
        setStepId: ({ stepId }, _, __, previousState) => {
            // kea listeners receive (payload, breakpoint, action, previousState). We need
            // the 4th arg here, not the 2nd — that was the breakpoint function.
            const previousStepId = selectors.stepId(previousState)
            if (!previousStepId || previousStepId === stepId) {
                actions.markStepsVisited([stepId].filter(Boolean))
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
                // collapsed via the dedup pass. Only fire once per task id
                // (markTaskAsCompleted is presumed idempotent server-side, but no
                // point hammering it).
                const setup = globalSetupLogic.findMounted()
                if (setup) {
                    const ticked = new Set<SetupTaskId>()
                    for (const step of flow.slice(previousIndex, nextIndex)) {
                        const ids: (SetupTaskId | undefined)[] = [
                            step.setupTaskId,
                            ...(step.additionalSetupTaskIds ?? []),
                        ]
                        for (const id of ids) {
                            if (id && !ticked.has(id)) {
                                ticked.add(id)
                                setup.actions.markTaskAsCompleted(id)
                            }
                        }
                    }
                }
            } else {
                // Backward / lateral / outside-flow movement: still record the new step as visited.
                actions.markStepsVisited([stepId].filter(Boolean))
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
            // Preserve any unrelated query params already on the URL (`?sdk=python`,
            // `?handoff=mobile`, billing-callback `?success=true`, etc.). The legacy
            // implementation merged via `...router.values.searchParams`; replicating
            // that contract avoids breaking deep-link conversions.
            const existingParams = router.values.searchParams ?? {}
            const { step: _drop1, with: _drop2, productKey: _drop3, ...passthrough } = existingParams
            void _drop1
            void _drop2
            void _drop3
            const url = urls.onboarding({
                productKey: values.productKey ?? undefined,
                step: stepId || undefined,
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
            // Backwards-compat: pre-refactor links used `?secondary=...`. Read both, with
            // `with` taking precedence when present.
            const withRaw = params.with ?? params.secondary

            if (success || upgraded) {
                actions.setSubscribedDuringOnboarding(true)
            }

            if (productKey !== values.productKey) {
                actions.setProductKey(productKey as ProductKey)
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
            if (values.productKey !== null) {
                actions.setProductKey(null)
            }
            actions.resetOnboardingFlowState()
        },
    })),
])
