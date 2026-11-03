import { RedisV2 } from '~/common/redis/redis-v2'
import { RedisConnectionConfig, RedisPoolConfig } from '~/common/utils/db/redis'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { TeamManager } from '~/common/utils/team-manager'

import { DeadlineSlots } from '../../utils/deadline-slots'

export interface SandboxEmailSenderConfig {
    enabled: boolean
    tenantName: string
    configurationSetName: string
    fromAddress: string
}

const ROUTE_SETTING_NAMES = {
    tenantName: 'SES_SANDBOX_TENANT_NAME',
    configurationSetName: 'SES_SANDBOX_CONFIGURATION_SET',
    fromAddress: 'SES_SANDBOX_FROM_ADDRESS',
} as const

function emptyRouteSettings(config: SandboxEmailSenderConfig): string[] {
    return (Object.keys(ROUTE_SETTING_NAMES) as (keyof typeof ROUTE_SETTING_NAMES)[])
        .filter((setting) => !config[setting].trim())
        .map((setting) => ROUTE_SETTING_NAMES[setting])
}

export type SandboxEmailBlockReason = 'switch_off' | 'recipient_not_member' | 'recipient_unverified' | 'check_failed'

const BLOCKED_EVENT_WINDOW_SECONDS = 3600
// The send is already skipped when this runs, and the worker's batch waits for it, so a stalled
// store must not hold the invocation open.
const BLOCKED_EVENT_TIMEOUT_MS = 1000
// The deadline cannot cancel a store call, so a stalled call keeps its connection until the store answers.
// At most this many run at once, on a pool of their own this size; a capture waiting for a slot holds
// nothing and gives up at its deadline, so a burst against a healthy store keeps every event.
export const MAX_OPEN_STORE_CALLS = 10

export function sandboxBlockedEventRedisConfig(connection: RedisConnectionConfig): RedisPoolConfig {
    return {
        // Blocked events are optional telemetry, so a store that refuses these connections must not stop the worker.
        connection: { ...connection, exitOnRepeatedErrors: false },
        poolMinSize: 0,
        poolMaxSize: MAX_OPEN_STORE_CALLS,
    }
}

export class SandboxEmailSender {
    public readonly canSend: boolean
    private storeSlots = new DeadlineSlots(MAX_OPEN_STORE_CALLS)

    constructor(
        public readonly config: SandboxEmailSenderConfig,
        private teamManager: TeamManager,
        private blockedEventRedis: Pick<RedisV2, 'useClient'>
    ) {
        this.config = {
            ...config,
            tenantName: config.tenantName.trim(),
            configurationSetName: config.configurationSetName.trim(),
            fromAddress: config.fromAddress.trim(),
        }
        const emptySettings = emptyRouteSettings(config)
        if (config.enabled && emptySettings.length) {
            logger.error('The sandbox sender is switched on with empty route settings, so it skips every send', {
                emptySettings,
            })
        }
        this.canSend = config.enabled && !emptySettings.length
    }

    public async captureBlocked(
        teamId: number,
        isTest: boolean,
        reason: SandboxEmailBlockReason,
        blockedRecipientCount: number
    ): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<void>((resolve) => {
            timer = setTimeout(resolve, BLOCKED_EVENT_TIMEOUT_MS)
        })
        const capture = this.withStoreSlot(deadline, () =>
            this.captureBlockedEvent(teamId, isTest, reason, blockedRecipientCount)
        )
        try {
            if ((await Promise.race([capture.then(() => true), deadline.then(() => false)])) === false) {
                logger.warn('Gave up capturing a sandbox email event: the event store did not answer', { teamId })
            }
        } finally {
            clearTimeout(timer)
        }
    }

    private async withStoreSlot(deadline: Promise<void>, work: () => Promise<void>): Promise<void> {
        await this.storeSlots.run(deadline, work)
    }

    private async captureBlockedEvent(
        teamId: number,
        isTest: boolean,
        reason: SandboxEmailBlockReason,
        blockedRecipientCount: number
    ): Promise<void> {
        try {
            if (!(await this.isFirstBlockInWindow(teamId, isTest, reason))) {
                return
            }
            const team = await this.teamManager.getTeam(teamId)
            if (team) {
                captureTeamEvent(team, 'workflows sandbox email blocked', {
                    reason,
                    blocked_recipient_count: blockedRecipientCount,
                    is_test: isTest,
                })
            }
        } catch (error) {
            logger.warn('Could not capture sandbox email event', { teamId, error })
        }
    }

    private async isFirstBlockInWindow(
        teamId: number,
        isTest: boolean,
        reason: SandboxEmailBlockReason
    ): Promise<boolean> {
        const firstBlock = await this.blockedEventRedis.useClient(
            { name: 'sandbox-blocked-event', timeout: 1000 },
            (client) =>
                client.set(
                    `@posthog/workflows-sandbox-blocked/${teamId}/${reason}/${isTest ? 'test' : 'live'}`,
                    '1',
                    'EX',
                    BLOCKED_EVENT_WINDOW_SECONDS,
                    'NX'
                )
        )
        return firstBlock === 'OK'
    }
}
