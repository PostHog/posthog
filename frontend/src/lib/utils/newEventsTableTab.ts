// pinned: a session storage key, so renaming it drops the choice of every open tab
const TAB_NEW_EVENTS_TABLE_KEY = 'ph_new_events_schema'

export function getTabNewEventsTable(): boolean | null {
    try {
        const stored = window.sessionStorage.getItem(TAB_NEW_EVENTS_TABLE_KEY)
        return stored === null ? null : stored === '1'
    } catch {
        // Every API request reads this, and a document without storage access, such as an embed in a third-party
        // frame, throws on window.sessionStorage.
        return null
    }
}

export function storeTabNewEventsTable(enabled: boolean | null): void {
    if (enabled === null) {
        window.sessionStorage.removeItem(TAB_NEW_EVENTS_TABLE_KEY)
    } else {
        window.sessionStorage.setItem(TAB_NEW_EVENTS_TABLE_KEY, enabled ? '1' : '0')
    }
}
