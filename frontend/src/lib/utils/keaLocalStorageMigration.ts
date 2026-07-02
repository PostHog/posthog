// One-time migration of kea-localstorage keys after the navigation-3000 -> navigation
// merge (2026-07). Keys follow `logic.path.join('.') + '.' + reducerKey` (kea-localstorage
// defaults: no prefix, '.' separator). Safe to delete this file a few months after ship.
const PREFIX_MIGRATIONS: [string, string][] = [
    ['layout.navigation-3000.navigationLogic.', 'layout.navigation.navigationLogic.'],
    ['layout.navigation-3000.themeLogic.', 'layout.navigation.themeLogic.'],
    ['layout.navigation-3000.components.projectTreeLogic.', 'layout.panel-layout.ProjectTree.projectTreeLogic.'],
]

/** Must run before any kea logic builds, as kea-localstorage reads keys at reducer build time. */
export function migrateKeaLocalStorageKeys(): void {
    try {
        for (const key of Object.keys(window.localStorage)) {
            for (const [oldPrefix, newPrefix] of PREFIX_MIGRATIONS) {
                if (key.startsWith(oldPrefix)) {
                    const value = window.localStorage.getItem(key)
                    if (value !== null) {
                        // Overwrite: the -3000 value is the live one; anything already under the
                        // new key is a stale relic from before the navigation-3000 era.
                        window.localStorage.setItem(newPrefix + key.slice(oldPrefix.length), value)
                    }
                    window.localStorage.removeItem(key)
                }
            }
        }
    } catch {
        // localStorage unavailable (private browsing, disabled storage) — persisted UI state is best-effort
    }
}
