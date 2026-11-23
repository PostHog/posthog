import type { WarehouseLoginApi } from 'products/data_warehouse/frontend/generated/api.schemas'

const KIND_RANK: Record<string, number> = { root: 0, project_reader: 1, project_user: 1, other: 2 }
const ACCESS_RANK: Record<string, number> = { project_reader: 0, project_user: 1 }

/** Root first, then project logins by project and access (read only before read and write), then other logins. */
export function orderLogins(logins: WarehouseLoginApi[]): WarehouseLoginApi[] {
    return [...logins].sort(
        (a, b) =>
            (KIND_RANK[a.kind] ?? 3) - (KIND_RANK[b.kind] ?? 3) ||
            (a.team_id ?? 0) - (b.team_id ?? 0) ||
            (ACCESS_RANK[a.kind] ?? 0) - (ACCESS_RANK[b.kind] ?? 0) ||
            a.username.localeCompare(b.username)
    )
}
