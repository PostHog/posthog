// Which mounted editors currently want the shared schema catalog scoped to a connection, keyed by
// tab id. Several editors can be mounted at once (notebook SQL nodes, metrics, endpoints) on the
// same connection, so the last one out is the one that hands the catalog back unscoped.
const connectionScopeOwners = new Map<string, string>()

export function claimConnectionScope(tabId: string, connectionId: string | null | undefined): void {
    if (connectionId) {
        connectionScopeOwners.set(tabId, connectionId)
    } else {
        connectionScopeOwners.delete(tabId)
    }
}

// Drops this tab's claim and reports whether the scoped connection is now unclaimed.
export function releaseConnectionScope(tabId: string, scopedConnectionId: string | null): boolean {
    connectionScopeOwners.delete(tabId)
    return scopedConnectionId !== null && ![...connectionScopeOwners.values()].includes(scopedConnectionId)
}
