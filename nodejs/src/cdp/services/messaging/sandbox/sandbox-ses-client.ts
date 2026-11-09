import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'

import { formatMailbox } from '../email.service'
import { SandboxMessage } from './sandbox-message'

export type SandboxSendTags = {
    teamId: number
    hogFlowId: string
    invocationId: string
    actionId: string
    flowVersion: number
    isTest: boolean
}

export type SandboxSesResult =
    | { status: 'accepted'; messageId: string }
    | { status: 'retry'; reason: 'ses_throttled' | 'ses_transient' }
    | { status: 'failed'; reason: 'ses_rejected' }

export type SandboxSesSettings = { configurationSet: string; tenantName: string }

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
        try {
            const response = await this.client.send(this.buildCommand(message, tags))
            return response.MessageId
                ? { status: 'accepted', messageId: response.MessageId }
                : { status: 'retry', reason: 'ses_transient' }
        } catch (error) {
            return classifySesError(error)
        }
    }

    private buildCommand(message: SandboxMessage, tags: SandboxSendTags): SendEmailCommand {
        return new SendEmailCommand({
            FromEmailAddress: formatMailbox(message.from.name, message.from.address),
            Destination: { ToAddresses: [formatMailbox(message.to.name, message.to.address)] },
            ConfigurationSetName: this.settings.configurationSet,
            TenantName: this.settings.tenantName,
            EmailTags: [
                { Name: 'ph_sbx_team', Value: String(tags.teamId) },
                { Name: 'ph_sbx_flow', Value: tags.hogFlowId },
                { Name: 'ph_sbx_run', Value: tags.invocationId },
                { Name: 'ph_sbx_action', Value: tags.actionId },
                { Name: 'ph_sbx_version', Value: String(tags.flowVersion) },
                { Name: 'ph_sbx_test', Value: String(tags.isTest) },
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
