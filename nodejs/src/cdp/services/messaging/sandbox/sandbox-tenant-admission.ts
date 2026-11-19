export const TENANT_MAX_AGE_MS = 300_000
export const TENANT_FUTURE_TOLERANCE_MS = 30_000

const UNRESOLVED_STATUSES = new Set(['', 'UNKNOWN'])

export type SandboxTenantMirror = { sendingStatus: string | null; syncedAt: Date | null }

export type TenantAdmission = { ok: true } | { ok: false; reason: 'pause_state_unavailable' | 'tenant_paused' }

export function admitTenant(tenant: SandboxTenantMirror, now: Date): TenantAdmission {
    if (
        tenant.sendingStatus === null ||
        UNRESOLVED_STATUSES.has(tenant.sendingStatus) ||
        !isFresh(tenant.syncedAt, now)
    ) {
        return { ok: false, reason: 'pause_state_unavailable' }
    }
    if (tenant.sendingStatus !== 'ENABLED') {
        return { ok: false, reason: 'tenant_paused' }
    }
    return { ok: true }
}

function isFresh(syncedAt: Date | null, now: Date): boolean {
    if (!syncedAt) {
        return false
    }
    const ageMs = now.getTime() - syncedAt.getTime()
    return ageMs <= TENANT_MAX_AGE_MS && ageMs >= -TENANT_FUTURE_TOLERANCE_MS
}
