// Dependency-free ids shared by the app shell and PostHog AI. Shell code imports them from here, so it does
// not statically load the AI panel components or the signals inbox logics to read a string.

// The client-side key for the embedded `taskTrackerSceneLogic` (and paired `runnerPanelLogic`) instance
// this panel binds. It stays stable so the panel keeps the same in-flight run across re-renders of its host.
export const MAX_SIDE_PANEL_ID = 'max-side-panel'

// Fixed panelId for the floating side panel chat, which is not a scene tab.
export const SIDE_PANEL_PANEL_ID = 'sidepanel'

/** The side panel option that shows the report chat. It round-trips through the URL hash. */
export const REPORT_AI_PANEL = 'inbox-report'

/** The side panel option that shows the scout chat. It round-trips through the URL hash. */
export const SCOUT_AI_PANEL = 'inbox-scout'

/**
 * Which PostHog AI implementation the Max scene renders. `'new'` is the posthog_ai/frontend surface
 * (the tasks product on `/ai`, the new composer + thread viewer in the side panel); `'legacy'` is the
 * existing Max chat. Only meaningful while the `PHAI_SANDBOX_MODE` flag is on. See `effectivePhaiView`
 * in `maxGlobalLogic`.
 */
export type PhaiViewMode = 'new' | 'legacy'
