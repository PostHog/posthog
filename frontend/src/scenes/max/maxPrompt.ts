// Dependency-free on purpose, like max-storage-keys.ts: call sites live in scene code
// (e.g. insight error states), where importing maxLogic itself would risk import cycles.

/**
 * Build the options string for `openSidePanel(SidePanelTab.Max, ...)` that makes the panel
 * auto-submit the prompt on open — the counterpart of the `!` prefix handled by
 * `parseCommandString` in maxLogic.
 */
export function autoRunMaxPrompt(prompt: string): string {
    return `!${prompt}`
}
