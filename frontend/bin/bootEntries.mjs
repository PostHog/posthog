// The boot chain's entry points. check-eager-graph.mjs measures them, and stableCssPlan.mjs puts the
// CSS they import statically into the eager layers, so both must name the same files.
export const ENTRY = 'src/index.tsx'
export const LOGGED_OUT_BOOT = [ENTRY, 'src/scenes/App.tsx', 'src/scenes/bootApp.ts']
export const AUTHENTICATED_SHELL = 'src/scenes/AuthenticatedShell.tsx'
export const BOOT_ENTRIES = [...LOGGED_OUT_BOOT, AUTHENTICATED_SHELL]
