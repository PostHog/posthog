import { PostgresRouter } from '~/common/utils/db/postgres'

import { IntegrationType } from '../../../types'
import { AcceptedSend } from '../../hogflows/transactional-email'
import { readSandboxAuthorization } from './sandbox-authorization'
import { admitTenant } from './sandbox-tenant-admission'

export type SandboxCodeSendRefusal =
    | 'sandbox_recipient_not_member'
    | 'sandbox_fields_unsupported'
    | 'sandbox_sender_unavailable'

export const SANDBOX_CODE_SEND_REFUSAL_STATUS: Record<SandboxCodeSendRefusal, number> = {
    sandbox_recipient_not_member: 422,
    sandbox_fields_unsupported: 400,
    sandbox_sender_unavailable: 403,
}

export type CodeSendSender =
    | { kind: 'own' }
    | { kind: 'email_sandbox' }
    | { kind: 'refused'; refusal: SandboxCodeSendRefusal }

export function senderOfCodeSend(
    teamId: number,
    send: AcceptedSend,
    integration: Pick<IntegrationType, 'team_id' | 'kind'> | null
): CodeSendSender {
    if (integration?.kind !== 'email_sandbox') {
        return { kind: 'own' }
    }
    if (integration.team_id !== teamId) {
        return { kind: 'refused', refusal: 'sandbox_sender_unavailable' }
    }
    const { cc, bcc, replyTo, from, attachments } = send
    if (cc?.length || bcc?.length || replyTo?.length || attachments?.length || from?.email || from?.name) {
        return { kind: 'refused', refusal: 'sandbox_fields_unsupported' }
    }
    return { kind: 'email_sandbox' }
}

export async function refuseSandboxCodeSend(
    db: PostgresRouter,
    {
        enabled,
        teamId,
        recipient,
        tenantName,
    }: { enabled: boolean; teamId: number; recipient: string; tenantName: string }
): Promise<SandboxCodeSendRefusal | null> {
    if (!enabled) {
        return 'sandbox_sender_unavailable'
    }
    const authorization = await readSandboxAuthorization(db, { teamId, recipient: recipient.trim(), tenantName })
    if (!authorization.ok) {
        switch (authorization.reason) {
            case 'not_member':
            case 'ambiguous_member':
                return 'sandbox_recipient_not_member'
            case 'organization_blocked':
            case 'team_not_found':
                return 'sandbox_sender_unavailable'
            case 'authorization_unavailable':
                return null
        }
    }
    const tenant = admitTenant(authorization.tenant, new Date())
    return !tenant.ok && tenant.reason === 'tenant_paused' ? 'sandbox_sender_unavailable' : null
}
