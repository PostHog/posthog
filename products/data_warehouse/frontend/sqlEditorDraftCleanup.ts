export const DRAFT_KEY_PREFIX = 'sql-editor-draft:'

export function clearSQLEditorDrafts(): void {
    for (const storageName of ['localStorage', 'sessionStorage'] as const) {
        try {
            const storage = window[storageName]
            for (let index = storage.length - 1; index >= 0; index--) {
                const key = storage.key(index)
                if (key?.startsWith(DRAFT_KEY_PREFIX)) {
                    storage.removeItem(key)
                }
            }
        } catch {
            // Disabled storage must not prevent logout or cleanup of the other store.
        }
    }
}

export function clearSQLEditorDraftFromStorageEvent(event: StorageEvent): void {
    try {
        if (event.storageArea === localStorage && event.key?.startsWith(DRAFT_KEY_PREFIX) && event.newValue === null) {
            sessionStorage.removeItem(event.key)
        }
    } catch {
        // Session storage can be disabled by the browser.
    }
}
