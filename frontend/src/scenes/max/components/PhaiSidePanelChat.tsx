import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

// The client-side key for the embedded `taskTrackerSceneLogic` (and paired `runnerPanelLogic`) instance
// this panel binds — stable so the panel keeps the same in-flight run across re-renders of its host.
export const MAX_SIDE_PANEL_ID = 'max-side-panel'

/**
 * The new posthog_ai side-panel experience: task-based, built on the `products/posthog_ai/frontend` runner
 * surface (composer -> pending thread -> live run) rather than Max's conversation logics
 * (`maxThreadLogic`/`askMax`/the conversations API). The legacy conversation chat remains behind the
 * `effectivePhaiView` toggle (see `maxGlobalLogic`). `scenes/max` hosts this only until the Max scene is
 * replaced outright by the posthog_ai product surface.
 */
export function PhaiSidePanelChat(): JSX.Element {
    return (
        <div className="flex flex-col h-full min-h-0">
            <SidePanelRunner panelId={MAX_SIDE_PANEL_ID} />
        </div>
    )
}
