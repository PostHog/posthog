import { HogFunctionType, IntegrationType } from '~/cdp/types'

import { EmailSendingSuspensionCause, TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import { EmailSuppressionService } from './email-suppression.service'
import { EmailValidationService, Undeliverable } from './email-validation.service'

export type PolicyCode =
    | 'sending_suspended'
    | 'template_paused'
    | 'sender_not_verified'
    | 'invalid_recipient'
    | 'recipient_suppressed'

type Rejection = {
    ok: false
    /** What happened, as the run log shows it. */
    detail: string
    why: string
    fix: string
}

export type PolicyRejection =
    | (Rejection & { code: Exclude<PolicyCode, 'sending_suspended'> })
    | (Rejection & { code: 'sending_suspended'; cause: EmailSendingSuspensionCause })

export type PolicyDecision = { ok: true; sender: IntegrationType } | PolicyRejection

export type SendCandidate = {
    teamId: number
    /** The synthetic hog function's metadata, where the workflow's email pause is stamped. */
    workflowMetadata: HogFunctionType['metadata']
    /** The sender integration the send resolved to, or null when it no longer exists. */
    sender: IntegrationType | null
    /** Every address the provider will deliver to: to, cc and bcc. */
    recipients: string[]
}

const CONTACT_SUPPORT = 'Contact support to get sending re-enabled.'

/**
 * The checks that decide whether an email may be sent, in one place for the API's admission and the
 * worker's delivery. A failed check names its code with why and fix, and the caller decides how to
 * present it.
 */
export class EmailSendPolicy {
    /**
     * `addresses` checks that each recipient can receive email at all. Delivery already skips those
     * recipients before this policy runs, so only the API's admission passes it.
     */
    constructor(
        private teamWorkflowsConfigService: Pick<TeamWorkflowsConfigService, 'getEmailSendingSuspension'>,
        private emailSuppressionService: Pick<EmailSuppressionService, 'isSuppressed'>,
        private addresses: Pick<EmailValidationService, 'findUndeliverable'> | null = null
    ) {}

    public async check(send: SendCandidate): Promise<PolicyDecision> {
        // Team-level kill switches: staff suspend all workflow email for a team whose sender reputation
        // endangers shared SES deliverability, and AWS pauses the team's SES tenant for the same underlying
        // reason. A paused tenant rejects every send, so gating here turns wasted invocations into one clear skip.
        const suspension = await this.teamWorkflowsConfigService.getEmailSendingSuspension(send.teamId)
        if (suspension) {
            return sendingSuspended(suspension)
        }
        const paused = workflowPaused(send.workflowMetadata)
        if (paused) {
            return paused
        }
        const sender = usableSender(send.sender, send.teamId)
        if ('code' in sender) {
            return sender
        }
        return (
            (await this.recipientsUndeliverable(send.teamId, send.recipients)) ??
            (await this.recipientsSuppressed(send.teamId, send.recipients)) ?? { ok: true, sender }
        )
    }

    private async recipientsUndeliverable(teamId: number, recipients: string[]): Promise<PolicyRejection | null> {
        const addresses = this.addresses
        if (!addresses) {
            return null
        }
        const verdicts = await Promise.all(recipients.map((email) => addresses.findUndeliverable(email, teamId)))
        const undeliverable = verdicts.find((verdict) => verdict !== null)
        return undeliverable ? invalidRecipient(undeliverable) : null
    }

    private async recipientsSuppressed(teamId: number, recipients: string[]): Promise<PolicyRejection | null> {
        const suppressed = await findSuppressedRecipients(this.emailSuppressionService, teamId, recipients)
        if (suppressed.length === 0) {
            return null
        }
        return {
            ok: false,
            code: 'recipient_suppressed',
            detail: `Skipping send: recipient(s) on the suppression list — ${suppressed.join(', ')}`,
            why: `An earlier email to ${suppressed.join(', ')} bounced or was marked as spam, so PostHog no longer sends to it.`,
            fix: 'Send to another address, or remove the address from the suppression list once it can receive email again.',
        }
    }
}

/** The suppressed addresses among the recipients. Suppression applies to every message category. */
export async function findSuppressedRecipients(
    emailSuppressionService: Pick<EmailSuppressionService, 'isSuppressed'>,
    teamId: number,
    recipients: string[]
): Promise<string[]> {
    const results = await Promise.all(
        recipients.map(async (email) => ({
            email,
            suppressed: await emailSuppressionService.isSuppressed(teamId, email),
        }))
    )
    return results.filter((result) => result.suppressed).map((result) => result.email)
}

function sendingSuspended(cause: EmailSendingSuspensionCause): PolicyRejection {
    if (cause === 'staff') {
        return {
            ok: false,
            code: 'sending_suspended',
            cause,
            detail: `Skipping send: email sending is suspended for this project. ${CONTACT_SUPPORT}`,
            why: 'Email sending is suspended for this project.',
            fix: CONTACT_SUPPORT,
        }
    }
    return {
        ok: false,
        code: 'sending_suspended',
        cause,
        detail: 'Skipping send: our email provider paused sending for this project. Check the Reputation tab to see what to fix.',
        why: 'Our email provider paused sending for this project.',
        fix: 'Check the Reputation tab to see what to fix.',
    }
}

/**
 * Stamped into the synthetic hog function's metadata by HogFlowFunctionsService, which is the only
 * flow-level state in scope at delivery. The `HogFlow` post_save signal publishes a worker config reload
 * when the pause is written, so an in-flight run and an already-queued batch send both stop here.
 */
function workflowPaused(metadata: HogFunctionType['metadata']): PolicyRejection | null {
    if (!metadata?.email_sending_paused_at) {
        return null
    }
    const reason = typeof metadata.email_sending_paused_reason === 'string' ? metadata.email_sending_paused_reason : ''
    const pauseDetail = reason ? ` ${reason}` : ''
    if (metadata.email_sending_paused_by === 'staff') {
        return {
            ok: false,
            code: 'template_paused',
            detail: `Skipping send: PostHog staff paused email sending for this workflow.${pauseDetail} ${CONTACT_SUPPORT}`,
            why: `PostHog staff paused email sending for this email's workflow.${pauseDetail}`,
            fix: CONTACT_SUPPORT,
        }
    }
    const fix = 'Resume it from the workflow page once the audience is cleaned up.'
    return {
        ok: false,
        code: 'template_paused',
        detail: `Skipping send: email sending is paused for this workflow.${pauseDetail} ${fix}`,
        why: `Email sending is paused for this email's workflow.${pauseDetail}`,
        fix,
    }
}

function usableSender(sender: IntegrationType | null, teamId: number): IntegrationType | PolicyRejection {
    // Wrong-team references deliberately read as not-found so an ID's existence on another team can't be probed
    if (!sender || sender.team_id !== teamId) {
        return senderNotVerified(
            "Email integration not found. The sender configured for this step no longer exists — select a new sender in the workflow's email step.",
            'The sender configured for this email no longer exists.',
            'Select a new sender for the email.'
        )
    }
    if (sender.kind !== 'email') {
        return senderNotVerified(
            "The integration configured for this step is not an email channel — select an email sender in the workflow's email step.",
            'The sender configured for this email is not an email channel.',
            'Select an email sender for the email.'
        )
    }
    if (!sender.config.verified) {
        return senderNotVerified(
            'The selected email integration domain is not verified',
            "The sender's domain is not verified.",
            'Verify the domain in the email channel settings, then send again.'
        )
    }
    if (!sender.config.email || !sender.config.name) {
        return senderNotVerified(
            'The selected email integration is not configured correctly',
            'The sender has no address or no name.',
            'Set the address and name of the sender in the email channel settings.'
        )
    }
    return sender
}

function invalidRecipient(undeliverable: Undeliverable): PolicyRejection {
    const why =
        undeliverable.reason === 'invalid_syntax'
            ? `\`${undeliverable.address}\` is not a valid email address.`
            : `The domain \`${undeliverable.domain}\` has no mail servers, so an email to \`${undeliverable.address}\` would bounce.`
    return {
        ok: false,
        code: 'invalid_recipient',
        detail: undeliverable.message,
        why,
        fix: 'Check the address for a typo. If it is right, the recipient cannot receive email, so skip them.',
    }
}

function senderNotVerified(detail: string, why: string, fix: string): PolicyRejection {
    return { ok: false, code: 'sender_not_verified', detail, why, fix }
}
