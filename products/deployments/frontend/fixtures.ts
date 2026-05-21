/**
 * Shared types + small UI helpers for the Deployments product.
 *
 * Re-exports the canonical generated API types as the names the rest of the
 * scene uses today (`Deployment`, `DeploymentStatus`). Backend-driven filters
 * mean we no longer apply them client-side — see `deploymentProjectsDeploymentsList`
 * in `./generated/api.ts` for the wire shape.
 */
import { DeploymentApi, DeploymentProjectApi, DeploymentStatusEnumApi } from './generated/api.schemas'

export type Deployment = DeploymentApi
export type DeploymentProject = DeploymentProjectApi
export type DeploymentStatus = DeploymentStatusEnumApi
export { DeploymentStatusEnumApi }

export interface DeploymentsFilters {
    search: string
    status: DeploymentStatus[]
    /** Single email — backend supports one author at a time via `author=<email>`. */
    author: string | null
    order: string
    page: number
}

export const DEPLOYMENTS_PER_PAGE = 50

export const DEFAULT_DEPLOYMENT_FILTERS: DeploymentsFilters = {
    search: '',
    status: [],
    author: null,
    order: '-created_at',
    page: 1,
}

export function formatDuration(seconds: number | null | undefined): string {
    if (seconds == null) {
        return '—'
    }
    if (seconds < 60) {
        return `${seconds}s`
    }
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return s === 0 ? `${m}m` : `${m}m ${s}s`
}
