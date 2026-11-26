import { SESv2Client, SESv2ClientConfig, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { NodeHttpHandler } from '@smithy/node-http-handler'
import { Counter, Histogram } from 'prom-client'

import { LoadedAttachment, settleBeforeAbortEvenWhileCredentialsStall } from './attachment-store'

export type { MessageHeader } from '@aws-sdk/client-sesv2'

export type SesEmail = SendEmailCommandInput

export type SesClientOptions = Pick<
    SESv2ClientConfig,
    'region' | 'endpoint' | 'credentials' | 'retryStrategy' | 'maxAttempts'
>

export type SesSend = { email: SesEmail } | { email: SesEmail; files: LoadedAttachment[]; deadline: AbortSignal }

/**
 * SES error codes that signal a transient rate-limit shape — safe to retry
 * shortly after. `TooManyRequestsException` is the SES-v2-specific class;
 * `ThrottlingException` is a generic AWS SDK error code that can surface
 * from the underlying transport layer for the same condition (not exported
 * as a class for sesv2, so we match by `name`).
 *
 * `SendingPausedException` is *not* on this list — it signals a reputation
 * or account-state problem that won't recover in seconds. Retrying within
 * 500ms just burns reschedules; the job hard-fails instead, surfaces via
 * `email_failed`, and the underlying SES config needs operator attention.
 */
const SES_THROTTLE_ERROR_NAMES = ['TooManyRequestsException', 'ThrottlingException'] as const
export type SesThrottleErrorName = (typeof SES_THROTTLE_ERROR_NAMES)[number]

const SES_REFUSAL_NAMES = [
    'MessageRejected',
    'MailFromDomainNotVerifiedException',
    'AccountSuspendedException',
    'SendingPausedException',
    'LimitExceededException',
    'NotFoundException',
    'BadRequestException',
] as const
export type SesRefusalName = (typeof SES_REFUSAL_NAMES)[number]

// DNS and TCP connect errors. Each one means that the request never left this worker.
const ERRORS_BEFORE_CONNECT = ['ENOTFOUND', 'EAI_AGAIN', 'ECONNREFUSED'] as const
type ErrorBeforeConnect = (typeof ERRORS_BEFORE_CONNECT)[number]

export type SesSendOutcome =
    | { kind: 'accepted'; messageId: string }
    | { kind: 'not_sent'; reason: 'throttled'; errorName: SesThrottleErrorName; message: string }
    | { kind: 'not_sent'; reason: 'before_deadline'; cause: unknown }
    | { kind: 'not_sent'; reason: 'before_connect'; code: ErrorBeforeConnect; message: string }
    | { kind: 'refused'; errorName: SesRefusalName; message: string }
    | { kind: 'unknown'; message: string }

export type SesSendOutcomeKind = SesSendOutcome['kind']

export type SesSendOutcomeOf<K extends SesSendOutcomeKind> = Extract<SesSendOutcome, { kind: K }>

type SendKind = 'plain' | 'files'

type SendPolicy = {
    client: () => Partial<SESv2ClientConfig>
    withFilesLabel: 'true' | 'false'
    connectErrorsAreNotSent: boolean
}

// A send with files takes long enough that SES can take the email and its answer can get lost, for example in a
// reset or a 5xx after SES recorded it. An SDK retry then sends the email a second time. So the files client
// makes one attempt, on a new connection that no earlier request used, and only an error from before the connect
// counts as not sent. The agent options keep the SDK's own socket cap, because they are merged into its defaults.
const SEND_POLICIES = {
    plain: { client: () => ({}), withFilesLabel: 'false', connectErrorsAreNotSent: false },
    files: {
        client: () => ({
            maxAttempts: 1,
            retryStrategy: undefined,
            requestHandler: new NodeHttpHandler({ httpAgent: { keepAlive: false }, httpsAgent: { keepAlive: false } }),
        }),
        withFilesLabel: 'true',
        connectErrorsAreNotSent: true,
    },
} satisfies Record<SendKind, SendPolicy>

const MAY_HAVE_SENT_BEFORE_DEADLINE =
    'SES did not answer before the send deadline. It may have sent the email, so it is not sent again.'

const sesThrottleResponsesTotal = new Counter({
    name: 'cdp_ses_throttle_responses_total',
    help: 'SES API responses classified as throttle/rate-limit. Sustained nonzero rate means the local bucket is set too high vs. the SES quota.',
    labelNames: ['error_code'],
})

const sesSendResultsTotal = new Counter({
    name: 'cdp_ses_send_results_total',
    help: 'SES SendEmail calls by result: success, throttled (rescheduled, with the error code in cdp_ses_throttle_responses_total), a known SES error name, or other.',
    labelNames: ['result'],
})

const sesSendDurationMs = new Histogram({
    name: 'cdp_ses_send_duration_ms',
    help: 'Duration of the SES SendEmail call in milliseconds, by whether SES accepted the email (success or error) and whether it carried attachment files (with_files).',
    labelNames: ['result', 'with_files'],
    buckets: [25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 30_000],
})

const errorNameOf = (error: unknown): string | undefined => (error instanceof Error ? error.name : undefined)

const messageOf = (error: unknown): string => (error instanceof Error ? error.message : String(error))

const isOneOf = <T extends string>(names: readonly T[], name: string | undefined): name is T =>
    (names as readonly (string | undefined)[]).includes(name)

// Every other error name reads as `other`, so an unexpected SDK error cannot add a series.
function sendResultLabel(error: unknown): string {
    const name = errorNameOf(error)
    if (isOneOf(SES_THROTTLE_ERROR_NAMES, name)) {
        return 'throttled'
    }
    return isOneOf(SES_REFUSAL_NAMES, name) || name === 'TimeoutError' ? name : 'other'
}

const codeOf = (error: unknown): string | undefined => {
    const code = (error as { code?: unknown } | null | undefined)?.code
    return typeof code === 'string' ? code : undefined
}

function failureOf(
    error: unknown,
    policy: SendPolicy,
    deadline: AbortSignal | undefined,
    attempts: SendAttempts
): SesSendOutcome {
    if (deadline?.aborted) {
        return attempts.sesMayHaveAccepted()
            ? { kind: 'unknown', message: MAY_HAVE_SENT_BEFORE_DEADLINE }
            : { kind: 'not_sent', reason: 'before_deadline', cause: error }
    }
    const errorBeforeConnect = attempts.lastErrorBeforeConnect()
    if (policy.connectErrorsAreNotSent && errorBeforeConnect) {
        return { kind: 'not_sent', reason: 'before_connect', code: errorBeforeConnect, message: messageOf(error) }
    }
    const name = errorNameOf(error)
    if (isOneOf(SES_THROTTLE_ERROR_NAMES, name)) {
        sesThrottleResponsesTotal.inc({ error_code: name })
        return { kind: 'not_sent', reason: 'throttled', errorName: name, message: messageOf(error) }
    }
    if (isOneOf(SES_REFUSAL_NAMES, name)) {
        return { kind: 'refused', errorName: name, message: messageOf(error) }
    }
    return { kind: 'unknown', message: messageOf(error) }
}

const FIRST_STEP_AFTER_SIGNING = 'deserialize'

const BENEATH_THE_DESERIALIZER = 'low'

const sesRefused = (response: unknown): boolean => {
    const statusCode = (response as { statusCode?: number } | undefined)?.statusCode
    return statusCode !== undefined && (statusCode < 200 || statusCode >= 300)
}

type SendAttempts = {
    sesMayHaveAccepted: () => boolean
    lastErrorBeforeConnect: () => ErrorBeforeConnect | undefined
}

function trackAttempts(command: SendEmailCommand): SendAttempts {
    let attemptsSesMayHaveAccepted = 0
    let lastErrorBeforeConnect: ErrorBeforeConnect | undefined
    command.middlewareStack.add(
        (next) => async (args) => {
            attemptsSesMayHaveAccepted++
            lastErrorBeforeConnect = undefined
            try {
                const httpAnswer = await next(args)
                if (sesRefused(httpAnswer.response)) {
                    attemptsSesMayHaveAccepted--
                }
                return httpAnswer
            } catch (error) {
                // The code is read here, beneath the SDK's retry step. That step replaces an error that fails
                // `instanceof Error`, such as one from another realm in a test, with a copy that has no code.
                const code = codeOf(error)
                if (isOneOf(ERRORS_BEFORE_CONNECT, code)) {
                    attemptsSesMayHaveAccepted--
                    lastErrorBeforeConnect = code
                }
                throw error
            }
        },
        { step: FIRST_STEP_AFTER_SIGNING, priority: BENEATH_THE_DESERIALIZER, name: 'trackAttempts' }
    )
    return {
        sesMayHaveAccepted: () => attemptsSesMayHaveAccepted > 0,
        lastErrorBeforeConnect: () => lastErrorBeforeConnect,
    }
}

function withAttachments(email: SesEmail, files: LoadedAttachment[]): SesEmail {
    if (!email.Content?.Simple || files.length === 0) {
        return email
    }
    const Attachments = files.map(({ file, bytes }) => ({
        RawContent: bytes,
        FileName: file.filename,
        ContentType: file.contentType,
        ContentId: file.contentId,
        ContentDisposition: file.contentId ? ('INLINE' as const) : ('ATTACHMENT' as const),
        ContentTransferEncoding: 'BASE64' as const,
    }))
    return { ...email, Content: { ...email.Content, Simple: { ...email.Content.Simple, Attachments } } }
}

export class SesTransport {
    private readonly clients: Record<SendKind, SESv2Client>

    constructor(options: SesClientOptions) {
        this.clients = {
            plain: new SESv2Client({ ...options, ...SEND_POLICIES.plain.client() }),
            files: new SESv2Client({ ...options, ...SEND_POLICIES.files.client() }),
        }
    }

    async send(send: SesSend): Promise<SesSendOutcome> {
        const kind: SendKind = 'files' in send ? 'files' : 'plain'
        const deadline = 'files' in send ? send.deadline : undefined
        const command = new SendEmailCommand('files' in send ? withAttachments(send.email, send.files) : send.email)
        const attempts = trackAttempts(command)
        const startedAt = performance.now()
        const observeDuration = (result: 'success' | 'error'): void =>
            sesSendDurationMs
                .labels({ result, with_files: SEND_POLICIES[kind].withFilesLabel })
                .observe(performance.now() - startedAt)
        try {
            const response = deadline
                ? await settleBeforeAbortEvenWhileCredentialsStall(
                      deadline,
                      this.clients[kind].send(command, { abortSignal: deadline })
                  )
                : await this.clients[kind].send(command)
            if (!response.MessageId) {
                throw new Error('No messageId returned from SES')
            }
            observeDuration('success')
            sesSendResultsTotal.inc({ result: 'success' })
            return { kind: 'accepted', messageId: response.MessageId }
        } catch (error: unknown) {
            observeDuration('error')
            sesSendResultsTotal.inc({ result: sendResultLabel(error) })
            return failureOf(error, SEND_POLICIES[kind], deadline, attempts)
        }
    }

    destroy(): void {
        Object.values(this.clients).forEach((client) => client.destroy())
    }
}

export type SandboxSesSender = { send(email: SesEmail, abortSignal: AbortSignal): Promise<{ MessageId?: string }> }

export function createSandboxSesSender(options: SesClientOptions): SandboxSesSender {
    const client = new SESv2Client({ ...options, maxAttempts: 1 })
    return { send: (email, abortSignal) => client.send(new SendEmailCommand(email), { abortSignal }) }
}
