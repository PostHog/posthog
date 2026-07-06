import { type SetupTaskId } from 'lib/components/ProductSetup'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingType, OnboardingStepKey, type TeamPublicType, type TeamType } from '~/types'

/**
 * A unit of work in an onboarding flow. Pure data — composes deterministically from
 * (selectedProducts, currentTeam, billing, ...) into a flat list rendered one at a
 * time. Replaces the old "JSX children of a per-product *Onboarding view" pattern.
 */
export interface OnboardingStepDescriptor {
    /** Unique within a flow. Format: `<stepKey>:<productKey>`. e.g. `install:web_analytics`. */
    id: string
    /** Which product this step belongs to (drives completion bookkeeping + breadcrumb attribution). */
    productKey: ProductKey
    /** Type of step, used for analytics events (`reportOnboardingStepCompleted`) and the default label. */
    stepKey: OnboardingStepKey
    /** Override for the breadcrumb/title label. Defaults to `stepKeyToTitle(stepKey)`. */
    label?: string
    /** Whether this step belongs to the primary product the user is onboarding into, or a secondary one. */
    role: 'primary' | 'secondary'
    /** Returns the React element to render for this step. */
    render: () => React.ReactElement
    /**
     * If set, advancing past this step ticks the matching task in PRODUCT_SETUP_REGISTRY
     * (via globalSetupLogic). Bridges onboarding completion into the post-onboarding setup checklist.
     */
    setupTaskId?: SetupTaskId
    /**
     * Optional flow-level dedup key. When two descriptors in the same flow share a
     * `dedupKey`, only the first occurrence is kept. Use it to collapse install steps
     * that are functionally identical — e.g. every posthog-js-based product's install
     * step uses `dedupKey: "install:posthog-js"`, so picking Product Analytics + Web
     * Analytics + Session Replay shows one Install step, not three.
     */
    dedupKey?: string
    /**
     * Auto-populated by the flow selector during the dedup pass: setup task ids from
     * descriptors that were dropped because they shared a `dedupKey` with this one.
     * The setStepId listener ticks all of them when the user advances past this step,
     * so dropped products still get their setup-checklist task marked complete.
     * Providers should NOT set this directly.
     */
    additionalSetupTaskIds?: SetupTaskId[]
    /**
     * Auto-populated by the flow selector during the dedup pass: product keys from
     * descriptors that were dropped because they shared a `dedupKey` with this one.
     * `completeOnboarding` credits these products as visited when the user advances
     * past this step, so dropped secondaries still flip `has_completed_onboarding_for`.
     * Providers should NOT set this directly.
     */
    additionalProductKeys?: ProductKey[]
}

export interface OnboardingFlowContext {
    primary: ProductKey
    secondaries: ProductKey[]
    /** Set per-product as the registry iterates. Each provider call sees its own role. */
    role: 'primary' | 'secondary'
    currentTeam: TeamType | TeamPublicType | null
    billing: BillingType | null
    isCloudOrDev: boolean
    subscribedDuringOnboarding: boolean
    /** Members can invite teammates — drives the trailing invite step. */
    canInviteTeammates: boolean
}

export type StepProvider = (ctx: OnboardingFlowContext) => OnboardingStepDescriptor[]

/**
 * Per-product registration unit for the onboarding system. Wires a product into
 * the flow with everything the central machinery needs to know:
 *
 *  - `steps`: how to build the product's contribution to the flow.
 *  - `completeRedirectUrl`: where to send the user after their onboarding for
 *    this product completes (was previously a central switch in onboardingLogic).
 *
 * Co-locating both here means adding a product is a single-file change inside
 * `products/<name>/frontend/onboarding/steps.tsx` plus a registry entry — no
 * scattered switches to keep in sync.
 */
export interface ProductOnboardingProvider {
    steps: StepProvider
    /**
     * Where to redirect when this product's onboarding completes (used when this
     * product is the primary). Falls back to `urls.default()` if not provided.
     */
    completeRedirectUrl?: () => string
}

/**
 * Standard dedup keys for install steps. Products that share an SDK should use the
 * same key on their install descriptor so the user only has to install once.
 *
 *  - `INSTALL_POSTHOG_JS`: every product backed by `posthog-js` (the JS web SDK + its
 *    server/mobile counterparts in the same SDKInstructionsMap shape).
 *  - `INSTALL_OPENTELEMETRY`: products that send data via OTel collectors (currently
 *    Logs; expand as we add more).
 *
 * Products with a meaningfully-different install experience (different verification
 * target, custom install header) intentionally don't share these keys — e.g. LLM
 * Analytics waits for an "LLM generation" event, which is a stricter signal than
 * "any event ingested." Workflows ships a custom AI-wizard install header.
 */
export const INSTALL_DEDUP_KEYS = {
    POSTHOG_JS: 'install:posthog-js',
    OPENTELEMETRY: 'install:opentelemetry',
} as const
