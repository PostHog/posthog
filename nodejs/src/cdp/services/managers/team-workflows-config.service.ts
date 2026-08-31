import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { PubSub } from '~/common/utils/pubsub'

// Mirrors EmailTrackingConsentMode in products/workflows/backend/models/team_workflows_config.py
export type EmailTrackingConsentMode = 'off' | 'opt_out' | 'opt_in'

/**
 * Which switch blocks workflow email for a team. `staff` is our own kill switch; `provider` is
 * a paused AWS SES tenant, mirrored into the config row by the workflows backend.
 */
export type EmailSendingSuspensionCause = 'staff' | 'provider'

export type TeamWorkflowsConfig = {
    capture_workflows_engagement_events: boolean
    email_tracking_consent_mode: EmailTrackingConsentMode
    email_sending_suspended: boolean
    ses_tenant_provider_suspended: boolean
}

const DEFAULT_CONFIG: TeamWorkflowsConfig = {
    capture_workflows_engagement_events: false,
    email_tracking_consent_mode: 'off',
    email_sending_suspended: false,
    ses_tenant_provider_suspended: false,
}

/**
 * Reads `workflows_teamworkflowsconfig` rows. The Django side creates a row
 * lazily via `get_or_create_team_extension`, so a missing row means the team
 * has never opted in — return the default (engagement event capture off).
 */
export class TeamWorkflowsConfigService {
    private lazyLoader: LazyLoader<TeamWorkflowsConfig>

    constructor(
        private postgres: PostgresRouter,
        pubSub: PubSub
    ) {
        this.lazyLoader = new LazyLoader({
            name: 'team_workflows_config',
            refreshAgeMs: 2 * 60 * 1000,
            refreshJitterMs: 30 * 1000,
            loader: async (teamIds) => await this.fetchConfigs(teamIds),
        })
        // The refresh age alone would leave a team the provider paused still sending, and a
        // reinstated team still blocked, until its entry expired. The provider state sync announces
        // each change so the next send reads it. Staff kill-switch flips still wait out the age.
        pubSub.on<{ teamId: number }>('reload-team-workflows-config', ({ teamId }) => {
            this.lazyLoader.markForRefresh(String(teamId))
        })
    }

    public async get(teamId: number): Promise<TeamWorkflowsConfig> {
        return (await this.lazyLoader.get(String(teamId))) ?? DEFAULT_CONFIG
    }

    public async shouldCaptureEngagementEvents(teamId: number): Promise<boolean> {
        const config = await this.get(teamId)
        return config.capture_workflows_engagement_events
    }

    public async getEmailTrackingConsentMode(teamId: number): Promise<EmailTrackingConsentMode> {
        const config = await this.get(teamId)
        return config.email_tracking_consent_mode
    }

    /**
     * Which switch, if any, blocks workflow email for this team: the kill switch staff set when a
     * team's sender reputation puts shared SES deliverability at risk, or the team's AWS SES tenant
     * being paused by AWS. Returns null when sending is allowed. Fails open: a lookup error must
     * never block legitimate sends.
     */
    public async getEmailSendingSuspension(teamId: number): Promise<EmailSendingSuspensionCause | null> {
        try {
            const config = await this.get(teamId)
            if (config.email_sending_suspended) {
                return 'staff'
            }
            if (config.ses_tenant_provider_suspended) {
                return 'provider'
            }
            return null
        } catch (error) {
            logger.error('[TeamWorkflowsConfig] Failed to check email sending suspension', { teamId, error })
            return null
        }
    }

    private async fetchConfigs(teamIds: string[]): Promise<Record<string, TeamWorkflowsConfig>> {
        const result = await this.postgres.query<{
            team_id: number
            capture_workflows_engagement_events: boolean
            email_tracking_consent_mode: EmailTrackingConsentMode
            email_sending_suspended: boolean
            ses_tenant_provider_suspended: boolean
        }>(
            PostgresUse.COMMON_READ,
            // Only DISABLED blocks: ENABLED and REINSTATED both permit sending, and '' means the
            // tenant state has never been synced for this team.
            `SELECT team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                    email_sending_suspended_at IS NOT NULL AS email_sending_suspended,
                    ses_tenant_sending_status = 'DISABLED' AS ses_tenant_provider_suspended
             FROM workflows_teamworkflowsconfig
             WHERE team_id = ANY($1)`,
            [teamIds.map(Number)],
            'fetch-team-workflows-configs'
        )

        const configs: Record<string, TeamWorkflowsConfig> = {}
        for (const teamId of teamIds) {
            configs[teamId] = DEFAULT_CONFIG
        }
        for (const row of result.rows) {
            configs[String(row.team_id)] = {
                capture_workflows_engagement_events: row.capture_workflows_engagement_events,
                email_tracking_consent_mode: row.email_tracking_consent_mode ?? 'off',
                email_sending_suspended: row.email_sending_suspended,
                ses_tenant_provider_suspended: row.ses_tenant_provider_suspended,
            }
        }
        return configs
    }
}
