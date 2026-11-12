import { LRUCache } from 'lru-cache'
import { PostHog } from 'posthog-node'
import { Counter } from 'prom-client'

import { unquoteMailbox } from '~/cdp/services/messaging/helpers/suppressed-recipients'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { captureTeamEvent } from '~/common/utils/posthog'
import { Team } from '~/types'

type WorkflowsActivationEvents = {
    'workflows send blocked': { workflow_id: string; channel: 'email'; reason: 'quota_limited' | 'missing_recipient' }
    'workflows send failed': { workflow_id: string; channel: 'email'; reason: 'unverified_domain' }
    'workflows message sent': { workflow_id: string; channel: 'email' | 'push'; recipient_outside_org: boolean }
}

const REPORT_INTERVAL_MS = 60 * 60 * 1000
const ORGANIZATION_MEMBERS_REFRESH_MS = 10 * 60 * 1000
export const MAX_PENDING_EMAIL_REPORTS = 1000
const ORGANIZATION_MEMBERS_RETRY_MS = 60 * 1000

const counterEmailReportsDropped = new Counter({
    name: 'cdp_workflows_activation_email_reports_dropped',
    help: 'Email sends that got no workflows message sent event because too many organization member reads were pending.',
})

export class WorkflowsActivationReporter {
    private lastReportedAt = new LRUCache<string, number>({ max: 50_000 })
    private organizationMemberEmails: LazyLoader<ReadonlySet<string>>
    private pendingEmailReports = 0
    private organizationMembersUnavailableUntil = 0

    constructor(
        private teamManager: { getTeam(teamId: number): Promise<Team | null> },
        private postgres: PostgresRouter,
        private analytics?: PostHog
    ) {
        this.organizationMemberEmails = new LazyLoader({
            name: 'workflows_activation_organization_member_emails',
            refreshAgeMs: ORGANIZATION_MEMBERS_REFRESH_MS,
            loader: (organizationIds) => this.fetchOrganizationMemberEmails(organizationIds),
        })
    }

    public async reportEmailSent(teamId: number, workflowId: string, recipients: string[]): Promise<void> {
        if (this.pendingEmailReports >= MAX_PENDING_EMAIL_REPORTS) {
            counterEmailReportsDropped.inc()
            return
        }
        this.pendingEmailReports++
        let recipientOutsideOrg: boolean | null
        try {
            recipientOutsideOrg = await this.isAnyRecipientOutsideOrganization(teamId, recipients)
        } finally {
            this.pendingEmailReports--
        }
        if (recipientOutsideOrg === null) {
            return
        }
        await this.report(teamId, 'workflows message sent', {
            workflow_id: workflowId,
            channel: 'email',
            recipient_outside_org: recipientOutsideOrg,
        })
    }

    public async reportPushSent(teamId: number, workflowId: string): Promise<void> {
        await this.report(teamId, 'workflows message sent', {
            workflow_id: workflowId,
            channel: 'push',
            recipient_outside_org: true,
        })
    }

    public async report<Event extends keyof WorkflowsActivationEvents>(
        teamId: number,
        event: Event,
        properties: WorkflowsActivationEvents[Event]
    ): Promise<void> {
        const key = reportKey(teamId, event, properties)
        const now = Date.now()
        const lastReportedAt = this.lastReportedAt.get(key)
        if (lastReportedAt !== undefined && now - lastReportedAt < REPORT_INTERVAL_MS) {
            return
        }
        this.lastReportedAt.set(key, now)

        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                this.lastReportedAt.delete(key)
                return
            }
            captureTeamEvent(team, event, properties, null, this.analytics)
        } catch (error) {
            this.lastReportedAt.delete(key)
            logger.warn('Failed to report a workflows activation event', { teamId, event, error })
        }
    }

    private async isAnyRecipientOutsideOrganization(teamId: number, recipients: string[]): Promise<boolean | null> {
        if (Date.now() < this.organizationMembersUnavailableUntil) {
            return null
        }
        try {
            const team = await this.teamManager.getTeam(teamId)
            if (!team) {
                return null
            }
            const memberEmails = await this.organizationMemberEmails.get(team.organization_id)
            return recipients.some((recipient) => !memberEmails?.has(recipient.toLowerCase()))
        } catch (error) {
            if (Date.now() >= this.organizationMembersUnavailableUntil) {
                logger.warn('Failed to read organization members for a workflows activation event', { teamId, error })
            }
            this.organizationMembersUnavailableUntil = Date.now() + ORGANIZATION_MEMBERS_RETRY_MS
            return null
        }
    }

    private async fetchOrganizationMemberEmails(
        organizationIds: string[]
    ): Promise<Record<string, ReadonlySet<string>>> {
        const { rows } = await this.postgres.query<{ organization_id: string; email: string }>(
            PostgresUse.COMMON_READ,
            `SELECT posthog_organizationmembership.organization_id, lower(posthog_user.email) AS email
             FROM posthog_organizationmembership
             JOIN posthog_user ON posthog_user.id = posthog_organizationmembership.user_id
             WHERE posthog_organizationmembership.organization_id = ANY($1::uuid[])`,
            [organizationIds],
            'fetchOrganizationMemberEmails'
        )
        const emailsByOrganization: Record<string, Set<string>> = {}
        for (const { organization_id, email } of rows) {
            ;(emailsByOrganization[organization_id] ??= new Set()).add(unquoteMailbox(email))
        }
        return emailsByOrganization
    }
}

function reportKey(teamId: number, event: string, properties: { workflow_id: string }): string {
    const { workflow_id: _workflowId, ...outcome } = properties
    return `${teamId}:${event}:${JSON.stringify(outcome, Object.keys(outcome).sort())}`
}
