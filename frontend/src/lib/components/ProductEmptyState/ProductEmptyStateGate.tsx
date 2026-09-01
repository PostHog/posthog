import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import type { ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ProductEmptyState } from './ProductEmptyState'
import { productSetupStatusLogic } from './productSetupStatusLogic'
import { SetupReminderContext } from './setupReminderContext'
import type { ProductEmptyStateConfig, ProductEmptyStateMode, SceneProductEmptyState } from './types'

/**
 * Search param that puts the setup screen on a scene that already has data, so anyone can
 * review an empty state without emptying a project. `?empty_state=1` shows the `needs-setup`
 * screen, `?empty_state=waiting-for-data` shows the other mode, and dropping the param
 * returns the real scene.
 */
export const EMPTY_STATE_PARAM = 'empty_state'

function forcedModeFromParam(value: unknown): ProductEmptyStateMode | null {
    if (value === 'waiting-for-data') {
        return 'waiting-for-data'
    }
    // kea-router parses search params before we see them, so `?empty_state=1` arrives as the
    // number 1 and a bare `?empty_state` as null. Match those forms exactly rather than any
    // truthy value, so a param we don't recognize leaves the real scene alone.
    if (value === null || value === 1 || value === true || value === '1' || value === 'true') {
        return 'needs-setup'
    }
    return null
}

export interface ProductEmptyStateGateProps {
    emptyState: SceneProductEmptyState
    children: ReactNode
}

/**
 * Gates scene content on the product's setup status:
 * - `loading` → hold a spinner (never flash the real scene before we know)
 * - `needs-setup` / `waiting-for-data` → the ProductEmptyState setup screen
 * - `has-data` / `unknown` (or the user skipped) → the scene, untouched
 *
 * Mounts the product's detection logic, which pushes its normalized status into
 * `productSetupStatusLogic`. Wired automatically by the app shell for scenes that
 * declare `emptyState` on their `SceneExport`.
 *
 * `?empty_state=1` on any gated scene forces the setup screen regardless of status,
 * so the screen can be reviewed on a project that already has data.
 */
export function ProductEmptyStateGate({ emptyState, children }: ProductEmptyStateGateProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    // When the empty state is flag-gated, stay a strict no-op while the flag is off —
    // don't even mount detection (the inner component is what mounts it).
    if (emptyState.featureFlag && !featureFlags[emptyState.featureFlag]) {
        return <>{children}</>
    }
    return <ProductEmptyStateGateInner emptyState={emptyState}>{children}</ProductEmptyStateGateInner>
}

function ProductEmptyStateGateInner({ emptyState, children }: ProductEmptyStateGateProps): JSX.Element {
    const { config, statusLogic } = emptyState
    useMountedLogic(statusLogic)
    const setupLogic = productSetupStatusLogic({ productKey: config.productKey })
    const { status, skipped, mode } = useValues(setupLogic)
    const { unskipEmptyState } = useActions(setupLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)
    const forcedMode = forcedModeFromParam(searchParams[EMPTY_STATE_PARAM])

    // A lingering local skip is ignored for non-skippable products (the button may have been
    // shown before the product opted out of skipping). Derived once, because the empty-state
    // branch below has to reach the same verdict: honoring the skip there but not here would
    // render the bare scene with neither the setup screen nor the reminder banner, and a
    // non-skippable product has no button left to clear the stored flag with.
    const skipHonored = skipped && config.skippable !== false

    // Forcing wins over skip, over the detected status, and over detection still loading.
    // The whole point is to see the screen on a project that would never show it on its own.
    if (forcedMode) {
        return (
            <ProductSceneFrame config={config}>
                <ProductEmptyState config={config} mode={forcedMode} />
            </ProductSceneFrame>
        )
    }

    if (skipHonored) {
        // Skip bypasses the screen, not detection: render the scene, plus a "Set up" reminder
        // until data lands, so there's always a way back to setup.
        const needsSetup = status === 'needs-setup' || status === 'waiting-for-data'
        const reminder = needsSetup ? (
            <LemonBanner
                type="info"
                action={{
                    children: `Set up ${config.productName}`,
                    onClick: unskipEmptyState,
                    'data-attr': 'product-empty-state-setup-banner',
                }}
            >
                {config.productName} isn't receiving data yet.
            </LemonBanner>
        ) : null
        // With the menu bar on, the reminder renders just below the bar (the scene's
        // SceneMenuBar consumes the context). With it off there is no consumer, so
        // render the banner here - otherwise a skipped product has no way back.
        if (featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
            return <SetupReminderContext.Provider value={reminder}>{children}</SetupReminderContext.Provider>
        }
        return (
            <>
                {reminder ? <div className="mb-4">{reminder}</div> : null}
                {children}
            </>
        )
    }
    if (status === 'loading') {
        // One consistent loading treatment app-wide, the same scene-level spinner shown while
        // scene chunks load. `productSetupPreloadLogic` answers this ahead of time only for
        // products that declare a `setupProbe` in their manifest, which is an event-based
        // signal. Entity-count products have none, so for them the spinner is the normal path
        // on every entry, including every trip back from a detail page.
        return (
            <ProductSceneFrame config={config}>
                <SpinnerOverlay sceneLevel />
            </ProductSceneFrame>
        )
    }
    if (!skipHonored && (status === 'needs-setup' || status === 'waiting-for-data')) {
        return (
            <ProductSceneFrame config={config}>
                <ProductEmptyState config={config} mode={mode} />
            </ProductSceneFrame>
        )
    }
    return <>{children}</>
}

/**
 * Keeps the product header above the empty state, sourced from the scene's own
 * `SceneConfig` (name, description, iconType from the product manifest).
 */
function ProductSceneFrame({
    config,
    children,
}: {
    config: ProductEmptyStateConfig
    children: ReactNode
}): JSX.Element {
    const { sceneConfig } = useValues(sceneLogic)
    return (
        <SceneContent>
            <SceneTitleSection
                name={sceneConfig?.name ?? config.productName}
                description={sceneConfig?.description ?? null}
                resourceType={
                    sceneConfig?.iconType
                        ? { type: sceneConfig.iconType }
                        : { type: String(config.productKey), forceIcon: config.icon }
                }
            />
            {children}
        </SceneContent>
    )
}
