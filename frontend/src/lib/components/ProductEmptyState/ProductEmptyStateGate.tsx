import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ProductEmptyState } from './ProductEmptyState'
import { productSetupStatusLogic } from './productSetupStatusLogic'
import { SetupReminderContext } from './setupReminderContext'
import type { ProductEmptyStateConfig, SceneProductEmptyState } from './types'

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
    const { status, skipped, showEmptyState, mode } = useValues(setupLogic)
    const { unskipEmptyState } = useActions(setupLogic)

    if (skipped) {
        // Skip bypasses the screen, not detection: render the scene, plus a "Set up" reminder
        // (via the SceneMenuBar) until data lands, so there's always a way back to setup.
        const needsSetup = status === 'needs-setup' || status === 'waiting-for-data'
        return (
            <SetupReminderContext.Provider
                value={
                    needsSetup ? (
                        <LemonBanner
                            type="info"
                            action={{ children: `Set up ${config.productName}`, onClick: unskipEmptyState }}
                        >
                            {config.productName} isn't receiving data yet.
                        </LemonBanner>
                    ) : null
                }
            >
                {children}
            </SetupReminderContext.Provider>
        )
    }
    if (status === 'loading') {
        // One consistent loading treatment app-wide — the same scene-level spinner
        // shown while scene chunks load. Statuses are preloaded at app boot (see
        // productSetupPreloadLogic), so this rarely renders in practice.
        return (
            <ProductSceneFrame config={config}>
                <SpinnerOverlay sceneLevel />
            </ProductSceneFrame>
        )
    }
    if (showEmptyState) {
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
 * `SceneConfig` (name, description, iconType from the product manifest) — the
 * same definition the rest of the app uses, so nothing is duplicated here.
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
