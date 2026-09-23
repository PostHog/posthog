import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import type { ComponentType, ReactNode } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    EMPTY_STATE_PARAM,
    activeProductEmptyStateGateRender,
    forcedModeFromParam,
    productEmptyStateGateActivation,
} from './gateRender'
import { ProductEmptyState } from './ProductEmptyState'
import { productSetupStatusLogic } from './productSetupStatusLogic'
import { SetupReminderContext } from './setupReminderContext'
import type { ProductEmptyStateConfig, SceneProductEmptyState } from './types'

export interface ProductEmptyStateGateProps {
    emptyState: SceneProductEmptyState
    /** The scene's route params, as passed to the scene component. Read by `scenes`. */
    params?: Record<string, string | undefined>
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
export function ProductEmptyStateGate({ emptyState, params, children }: ProductEmptyStateGateProps): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { searchParams } = useValues(router)
    const forcedMode = forcedModeFromParam(searchParams[EMPTY_STATE_PARAM])
    const { activeSceneId } = useValues(sceneLogic)

    // When the empty state is flag-gated or scoped to specific scenes or tabs, stay a strict
    // no-op otherwise — don't even mount detection (the inner component mounts it).
    const activation = productEmptyStateGateActivation({
        emptyState,
        activeSceneId,
        params: params ?? {},
        featureFlags,
        receivedFeatureFlags,
        forcedMode,
    })
    if (activation === 'off') {
        return <>{children}</>
    }
    if (activation === 'awaiting-flags') {
        return (
            <ProductSceneFrame config={emptyState.config} SceneNav={emptyState.SceneNav}>
                <SpinnerOverlay sceneLevel />
            </ProductSceneFrame>
        )
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

    // Has to reach the same verdict as the helper: a skip honored here but not there renders the
    // bare scene with neither the setup screen nor the reminder banner.
    const skipHonored = skipped && config.skippable !== false
    const gateRender = activeProductEmptyStateGateRender({ config, forcedMode, status, skipped })

    if (gateRender === 'setup') {
        return (
            <ProductSceneFrame config={config} SceneNav={emptyState.SceneNav}>
                <ProductEmptyState config={config} mode={forcedMode ?? mode} preview={!!forcedMode} />
            </ProductSceneFrame>
        )
    }
    if (gateRender === 'loading') {
        // One consistent loading treatment app-wide, the same scene-level spinner shown while
        // scene chunks load. `productSetupPreloadLogic` answers this ahead of time only for
        // products that declare a `setupProbe` in their manifest, which is an event-based
        // signal. Entity-count products have none, so for them the spinner is the normal path
        // on every entry, including every trip back from a detail page.
        return (
            <ProductSceneFrame config={config} SceneNav={emptyState.SceneNav}>
                <SpinnerOverlay sceneLevel />
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
    return <>{children}</>
}

/**
 * Keeps the product header above the empty state, sourced from the scene's own
 * `SceneConfig` (name, description, iconType from the product manifest).
 */
function ProductSceneFrame({
    config,
    SceneNav,
    children,
}: {
    config: ProductEmptyStateConfig
    SceneNav?: ComponentType
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
            {SceneNav ? <SceneNav /> : null}
            {children}
        </SceneContent>
    )
}
