import api, { ApiConfig } from 'lib/api'

import type { DashboardDocument } from '../document/dashboardTypes'

// TODO(2026-11-26): Replace with `dashboardV2BoardsRetrieve`, `dashboardV2BoardsUpdate` and `BoardDetailApi` from
// `products/dashboards/frontend/generated/`. The boards API is still in review in #142503, so this branch has no
// generated client for it yet.
export type Board = {
    uid: string
    /** Counts saves. A save sends it back as `base_version`, so it is refused when someone else saved in between. */
    version: number
    /** Only `native` boards are saved through the API. */
    managed_by: 'native' | 'builtin' | 'iac'
    spec: DashboardDocument
}

function boardUrl(uid: string): string {
    return `api/projects/${ApiConfig.getCurrentProjectId()}/dashboard_v2/boards/${encodeURIComponent(uid)}/`
}

export function getBoard(uid: string): Promise<Board> {
    // nosemgrep: prefer-codegen-api -- no generated client until #142503 lands, see the TODO above
    return api.get<Board>(boardUrl(uid))
}

/** Rejects with a 409 `ApiError` when the board is no longer at `baseVersion`. */
export function updateBoard(uid: string, spec: DashboardDocument, baseVersion: number): Promise<Board> {
    // nosemgrep: prefer-codegen-api -- no generated client until #142503 lands, see the TODO above
    return api.put<Board>(boardUrl(uid), { spec, base_version: baseVersion })
}
