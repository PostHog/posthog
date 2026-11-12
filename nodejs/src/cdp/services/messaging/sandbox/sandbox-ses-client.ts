import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'

import { logger } from '~/common/utils/logger'

import { settleBeforeAbortEvenWhileCredentialsStall } from '../attachment-store'
import { formatMailbox } from '../email.service'
import { SES_SEND_TIMEOUT_MS } from './sandbox-deadlines'
import { SandboxMessage } from './sandbox-message'

export const SANDBOX_SES_TAGS = {
    team: 'ph_sbx_team',
    flow: 'ph_sbx_flow',
    run: 'ph_sbx_run',
    action: 'ph_sbx_action',
    version: 'ph_sbx_version',
    test: 'ph_sbx_test',
    parentRun: 'ph_sbx_parent_run',
} as const

export const SES_TAG_ID = /^[A-Za-z0-9_-]{1,128}$/

export type SandboxSendTags = {
    teamId: number
    hogFlowId: string
    invocationId: string
    actionId: string
    flowVersion: number
    isTest: boolean
    parentRunId?: string
}

export type SandboxSesResult =
    | { status: 'accepted'; messageId: string }
    | { status: 'retry'; reason: 'ses_throttled' | 'ses_transient' }
    | { status: 'failed'; reason: 'ses_rejected' }

export type SandboxSesSettings = { configurationSet: string; tenantName: string; sendTimeoutMs?: number }

const THROTTLE_ERROR_NAMES = new Set(['ThrottlingException', 'TooManyRequestsException'])

export function createSandboxSesV2Client({ region, endpoint }: { region: string; endpoint: string }): SESv2Client {
    return new SESv2Client({ region, endpoint: endpoint || undefined, maxAttempts: 1 })
}

export class SandboxSesClient {
    constructor(
        private readonly client: Pick<SESv2Client, 'send'>,
        private readonly settings: SandboxSesSettings
    ) {}

    async send(message: SandboxMessage, tags: SandboxSendTags): Promise<SandboxSesResult> {
        const deadline = new AbortController()
        const timer = setTimeout(() => deadline.abort(), this.settings.sendTimeoutMs ?? SES_SEND_TIMEOUT_MS)
        try {
            const response = await settleBeforeAbortEvenWhileCredentialsStall(
                deadline.signal,
                this.client.send(this.buildCommand(message, tags), { abortSignal: deadline.signal })
            )
            return response.MessageId
                ? { status: 'accepted', messageId: response.MessageId }
                : { status: 'retry', reason: 'ses_transient' }
        } catch (error) {
            const metadata = (error as { $metadata?: { httpStatusCode?: number; requestId?: string } })?.$metadata
            logger.warn('Sandbox SES send failed', {
                error: error instanceof Error ? error.name : String(error),
                httpStatusCode: metadata?.httpStatusCode,
                requestId: metadata?.requestId,
                teamId: tags.teamId,
            })
            return classifySesError(error)
        } finally {
            clearTimeout(timer)
        }
    }

    private buildCommand(message: SandboxMessage, tags: SandboxSendTags): SendEmailCommand {
        return new SendEmailCommand({
            FromEmailAddress: formatMailbox(message.from.name, message.from.address),
            Destination: { ToAddresses: [formatMailbox(message.to.name, message.to.address)] },
            ConfigurationSetName: this.settings.configurationSet,
            TenantName: this.settings.tenantName,
            EmailTags: [
                { Name: SANDBOX_SES_TAGS.team, Value: String(tags.teamId) },
                { Name: SANDBOX_SES_TAGS.flow, Value: tags.hogFlowId },
                { Name: SANDBOX_SES_TAGS.run, Value: tags.invocationId },
                { Name: SANDBOX_SES_TAGS.action, Value: tags.actionId },
                { Name: SANDBOX_SES_TAGS.version, Value: String(tags.flowVersion) },
                { Name: SANDBOX_SES_TAGS.test, Value: String(tags.isTest) },
                ...(tags.parentRunId ? [{ Name: SANDBOX_SES_TAGS.parentRun, Value: tags.parentRunId }] : []),
            ],
            Content: {
                Simple: {
                    Subject: { Data: message.subject, Charset: 'UTF-8' },
                    Body: {
                        ...(message.text ? { Text: { Data: message.text, Charset: 'UTF-8' } } : {}),
                        ...(message.html ? { Html: { Data: message.html, Charset: 'UTF-8' } } : {}),
                    },
                    Headers: message.headers.map(({ name, value }) => ({ Name: name, Value: value })),
                },
            },
        })
    }
}

function classifySesError(error: unknown): SandboxSesResult {
    if (error instanceof Error && THROTTLE_ERROR_NAMES.has(error.name)) {
        return { status: 'retry', reason: 'ses_throttled' }
    }
    const statusCode = (error as { $metadata?: { httpStatusCode?: number } })?.$metadata?.httpStatusCode
    if (statusCode !== undefined && statusCode >= 400 && statusCode < 500) {
        return { status: 'failed', reason: 'ses_rejected' }
    }
    return { status: 'retry', reason: 'ses_transient' }
}
