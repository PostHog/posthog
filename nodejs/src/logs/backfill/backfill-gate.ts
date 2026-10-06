import { isFeatureFlagEnabled } from '~/common/utils/posthog'

export const LOGS_BACKFILL_FLAG = 'logs-backfill-enabled'

const REFRESH_MS = 60_000

type FlagCheck = (teamId: number) => Promise<boolean>

// The flag matches on the `project` group. The wrapper returns false on any failure, so the gate fails closed.
const checkBackfillFlag: FlagCheck = (teamId) =>
    isFeatureFlagEnabled(LOGS_BACKFILL_FLAG, String(teamId), {
        groups: { project: String(teamId) },
        sendFeatureFlagEvents: false,
    })

// Each check is a remote `/flags` request, so the answer is cached per team.
export class BackfillGate {
    private cache = new Map<number, { enabled: Promise<boolean>; fetchedAtMs: number }>()

    constructor(private check: FlagCheck = checkBackfillFlag) {}

    public isEnabledForTeam(teamId: number): Promise<boolean> {
        const now = Date.now()
        const cached = this.cache.get(teamId)
        if (cached && now - cached.fetchedAtMs < REFRESH_MS) {
            return cached.enabled
        }
        const enabled = this.check(teamId)
        this.cache.set(teamId, { enabled, fetchedAtMs: now })
        return enabled
    }
}
