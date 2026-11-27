import { SESv2Client, SESv2ClientConfig, SendEmailCommand, SendEmailCommandInput } from '@aws-sdk/client-sesv2'
import { Counter, Histogram } from 'prom-client'

import { LoadedAttachment, settleBeforeAbortEvenWhileCredentialsStall } from './attachment-store'

export type { MessageHeader } from '@aws-sdk/client-sesv2'

export type SesEmail = SendEmailCommandInput

export type SesClientOptions = Pick<
    SESv2ClientConfig,
    'region' | 'endpoint' | 'credentials' | 'retryStrategy' | 'maxAttempts'
>

export type SesSend = { email: SesEmail; files?: LoadedAttachment[]; deadline: AbortSignal }

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

export type SesSendOutcome =
    | { kind: 'accepted'; messageId: string }
    | { kind: 'not_sent'; reason: 'throttled'; errorName: SesThrottleErrorName; message: string }
    | { kind: 'not_sent'; reason: 'before_deadline'; cause: unknown }
    | { kind: 'refused'; errorName: SesRefusalName; message: string }
    | { kind: 'unknown'; message: string }

export type SesSendOutcomeKind = SesSendOutcome['kind']

export type SesSendOutcomeOf<K extends SesSendOutcomeKind> = Extract<SesSendOutcome, { kind: K }>

type SendKind = 'plain' | 'files'

const WITH_FILES_LABEL = { plain: 'false', files: 'true' } satisfies Record<SendKind, 'true' | 'false'>

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

export const isSesThrottle = (error: unknown): boolean => isOneOf(SES_THROTTLE_ERROR_NAMES, errorNameOf(error))

function boundedSendResultLabel(error: unknown): string {
    const name = errorNameOf(error)
    if (isOneOf(SES_THROTTLE_ERROR_NAMES, name)) {
        return 'throttled'
    }
    return isOneOf(SES_REFUSAL_NAMES, name) || name === 'TimeoutError' ? name : 'other'
}

function failureOf(error: unknown, deadline: AbortSignal, mayHaveReachedSes: boolean): SesSendOutcome {
    if (deadline.aborted) {
        return mayHaveReachedSes
            ? { kind: 'unknown', message: MAY_HAVE_SENT_BEFORE_DEADLINE }
            : { kind: 'not_sent', reason: 'before_deadline', cause: error }
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

function trackAttemptsSesMayHaveAccepted(command: SendEmailCommand): () => boolean {
    let attemptsSesMayHaveAccepted = 0
    command.middlewareStack.add(
        (next) => async (args) => {
            attemptsSesMayHaveAccepted++
            const httpAnswer = await next(args)
            if (sesRefused(httpAnswer.response)) {
                attemptsSesMayHaveAccepted--
            }
            return httpAnswer
        },
        { step: FIRST_STEP_AFTER_SIGNING, priority: BENEATH_THE_DESERIALIZER, name: 'trackAttemptsSesMayHaveAccepted' }
    )
    return () => attemptsSesMayHaveAccepted > 0
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
        const client = new SESv2Client(options)
        this.clients = { plain: client, files: client }
    }

    async send({ email, files = [], deadline }: SesSend): Promise<SesSendOutcome> {
        const kind: SendKind = files.length ? 'files' : 'plain'
        const command = new SendEmailCommand(withAttachments(email, files))
        const anAttemptSesMayHaveAccepted = trackAttemptsSesMayHaveAccepted(command)
        const startedAt = performance.now()
        const observeDuration = (result: 'success' | 'error'): void =>
            sesSendDurationMs
                .labels({ result, with_files: WITH_FILES_LABEL[kind] })
                .observe(performance.now() - startedAt)
        try {
            const response = await settleBeforeAbortEvenWhileCredentialsStall(
                deadline,
                this.clients[kind].send(command, { abortSignal: deadline })
            )
            if (!response.MessageId) {
                throw new Error('No messageId returned from SES')
            }
            observeDuration('success')
            sesSendResultsTotal.inc({ result: 'success' })
            return { kind: 'accepted', messageId: response.MessageId }
        } catch (error: unknown) {
            observeDuration('error')
            sesSendResultsTotal.inc({ result: boundedSendResultLabel(error) })
            return failureOf(error, deadline, anAttemptSesMayHaveAccepted())
        }
    }

    destroy(): void {
        new Set(Object.values(this.clients)).forEach((client) => client.destroy())
    }
}

export type SandboxSesSender = { send(email: SesEmail, abortSignal: AbortSignal): Promise<{ MessageId?: string }> }

export function createSandboxSesSender(
    options: Pick<SESv2ClientConfig, 'region' | 'endpoint' | 'credentials'>
): SandboxSesSender {
    const client = new SESv2Client({ ...options, maxAttempts: 1 })
    return { send: (email, abortSignal) => client.send(new SendEmailCommand(email), { abortSignal }) }
}
