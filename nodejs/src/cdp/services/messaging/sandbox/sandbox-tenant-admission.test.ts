import { SandboxTenantMirror, admitTenant } from './sandbox-tenant-admission'

const now = new Date('2026-01-01T12:00:00Z')
const secondsAgo = (seconds: number): Date => new Date(now.getTime() - seconds * 1000)

describe('admitTenant', () => {
    it.each<[string, SandboxTenantMirror, ReturnType<typeof admitTenant>]>([
        ['admits an enabled tenant synced just now', { sendingStatus: 'ENABLED', syncedAt: now }, { ok: true }],
        [
            'admits an enabled tenant synced five minutes ago',
            { sendingStatus: 'ENABLED', syncedAt: secondsAgo(300) },
            { ok: true },
        ],
        [
            'admits an enabled tenant synced within the clock skew allowance',
            { sendingStatus: 'ENABLED', syncedAt: secondsAgo(-30) },
            { ok: true },
        ],
        [
            'retries when the tenant has no mirror row',
            { sendingStatus: null, syncedAt: null },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
        [
            'retries when the mirror was never synced',
            { sendingStatus: 'ENABLED', syncedAt: null },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
        [
            'retries when the mirror is stale',
            { sendingStatus: 'ENABLED', syncedAt: secondsAgo(301) },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
        [
            'retries when the mirror is synced too far in the future',
            { sendingStatus: 'ENABLED', syncedAt: secondsAgo(-31) },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
        [
            'retries on an empty status',
            { sendingStatus: '', syncedAt: now },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
        [
            'retries when the poll could not find the tenant',
            { sendingStatus: 'UNKNOWN', syncedAt: now },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
        [
            'skips while the tenant is disabled',
            { sendingStatus: 'DISABLED', syncedAt: now },
            { ok: false, reason: 'tenant_paused' },
        ],
        [
            'skips while the tenant waits for reinstatement',
            { sendingStatus: 'REINSTATED_PENDING', syncedAt: now },
            { ok: false, reason: 'tenant_paused' },
        ],
        [
            'retries rather than trusting a stale pause',
            { sendingStatus: 'DISABLED', syncedAt: secondsAgo(301) },
            { ok: false, reason: 'pause_state_unavailable' },
        ],
    ])('%s', (_case, tenant, expected) => {
        expect(admitTenant(tenant, now)).toEqual(expected)
    })
})
