import { createHash } from 'crypto'
import { Counter, Histogram } from 'prom-client'
import { z } from 'zod'

import {
    CyclotronInvocationQueueParametersEmailType,
    EmailAttachmentMetadata,
    MAX_EMAIL_ATTACHMENTS,
} from '~/cdp/schema/cyclotron'

export const MAX_COPY_RECIPIENTS = 10

export const RECIPIENT_ADDRESS_PATTERN =
    /^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/

const CopyRecipientsSchema = z
    .array(z.string().email({ pattern: RECIPIENT_ADDRESS_PATTERN }))
    .max(MAX_COPY_RECIPIENTS)
    .readonly()
    .optional()

export const MAX_EMAIL_ATTACHMENTS_BYTES = 512 * 1024

const BLOCKED_ATTACHMENT_EXTENSIONS: ReadonlySet<string> = new Set([
    'ade',
    'adp',
    'apk',
    'app',
    'appx',
    'appxbundle',
    'asp',
    'bas',
    'bat',
    'cab',
    'cer',
    'chm',
    'cmd',
    'com',
    'cpl',
    'crt',
    'csh',
    'der',
    'diagcab',
    'diagcfg',
    'diagpkg',
    'dll',
    'dmg',
    'ex',
    'ex_',
    'exe',
    'fxp',
    'gadget',
    'hlp',
    'hta',
    'img',
    'inf',
    'ins',
    'iso',
    'isp',
    'its',
    'jar',
    'jnlp',
    'js',
    'jse',
    'ksh',
    'lib',
    'lnk',
    'mad',
    'maf',
    'mag',
    'mam',
    'maq',
    'mar',
    'mas',
    'mat',
    'mau',
    'mav',
    'maw',
    'mda',
    'mdb',
    'mde',
    'mdt',
    'mdw',
    'mdz',
    'mjs',
    'msc',
    'msh',
    'msh1',
    'msh1xml',
    'msh2',
    'msh2xml',
    'mshxml',
    'msi',
    'msix',
    'msixbundle',
    'msp',
    'mst',
    'nsh',
    'ops',
    'pcd',
    'pif',
    'plg',
    'prf',
    'prg',
    'ps1',
    'ps1xml',
    'ps2',
    'ps2xml',
    'psc1',
    'psc2',
    'reg',
    'scf',
    'scr',
    'sct',
    'shb',
    'shs',
    'sys',
    'tmp',
    'url',
    'vb',
    'vbe',
    'vbs',
    'vhd',
    'vps',
    'vsmacros',
    'vss',
    'vst',
    'vsw',
    'vxd',
    'ws',
    'wsc',
    'wsf',
    'wsh',
    'xll',
    'xnk',
])

const BASE64_RE = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/
const MIME_TYPE_RE = /^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$/i
const CONTROL_CHARACTER_RE = /[\x00-\x1F\x7F]/
const SES_ATTACHMENT_HEADER_MAX_LENGTH = 78

const AttachmentSchema = z
    .object({
        filename: z
            .string()
            .min(1)
            .max(255)
            .refine((name) => !/[\\/]/.test(name) && !CONTROL_CHARACTER_RE.test(name), {
                message: 'filename must not contain a path separator or a line break',
            })
            .refine(
                (name) => {
                    const dot = name.lastIndexOf('.')
                    return dot < 0 || !BLOCKED_ATTACHMENT_EXTENSIONS.has(name.slice(dot + 1).toLowerCase())
                },
                { message: 'mailbox providers block this file type' }
            ),
        content: z
            .string()
            .min(1, { message: 'content must not be empty' })
            .refine((content) => BASE64_RE.test(content), { message: 'content must be base64' }),
        contentType: z
            .string()
            .max(SES_ATTACHMENT_HEADER_MAX_LENGTH)
            .regex(MIME_TYPE_RE, { message: 'contentType must be a MIME type' })
            .optional(),
        contentId: z
            .string()
            .min(1)
            .max(SES_ATTACHMENT_HEADER_MAX_LENGTH)
            .refine((id) => !/[<>]/.test(id) && !CONTROL_CHARACTER_RE.test(id), {
                message: 'contentId must not contain < or > or a line break',
            })
            .optional(),
    })
    .strict()
    .readonly()

const AttachmentsSchema = z
    .array(AttachmentSchema)
    .max(MAX_EMAIL_ATTACHMENTS)
    .refine(
        (files) =>
            files.reduce((total, file) => total + Buffer.byteLength(file.content, 'base64'), 0) <=
            MAX_EMAIL_ATTACHMENTS_BYTES,
        { message: 'attachments must be 512 KB or less in total' }
    )
    .readonly()
    .optional()

export const AcceptedSendSchema = z
    .object({
        content: z
            .object({
                subject: z.string().min(1),
                html: z.string().optional(),
                text: z.string().optional(),
            })
            .strict()
            .readonly()
            .refine((content) => !!content.html || !!content.text, { message: 'content needs html or text' })
            .optional(),
        from: z
            .object({
                integrationId: z.number().int(),
                email: z.string().optional(),
                name: z.string().optional(),
            })
            .strict()
            .readonly()
            .optional(),
        replyTo: z.array(z.string()).readonly().optional(),
        cc: CopyRecipientsSchema,
        bcc: CopyRecipientsSchema,
        attachments: AttachmentsSchema,
        tracking: z.object({ captureEngagement: z.boolean() }).strict().readonly(),
    })
    .strict()
    .readonly()

export type AcceptedSend = z.infer<typeof AcceptedSendSchema>

export type QueuedSend = Omit<AcceptedSend, 'attachments'> & { attachments?: readonly EmailAttachmentMetadata[] }

export type DecodedAttachment = EmailAttachmentMetadata & { content: Buffer }

export const decodeAttachments = (send: AcceptedSend | undefined): DecodedAttachment[] =>
    (send?.attachments ?? []).map(({ filename, content, contentType, contentId }) => {
        const bytes = Buffer.from(content, 'base64')
        return {
            filename,
            ...(contentType !== undefined && { contentType }),
            ...(contentId !== undefined && { contentId }),
            sizeBytes: bytes.length,
            sha256: createHash('sha256').update(bytes).digest('hex'),
            content: bytes,
        }
    })

export const attachmentMetadata = (files: DecodedAttachment[]): EmailAttachmentMetadata[] =>
    files.map(({ content: _content, ...metadata }) => metadata)

export const queuedSend = (send: AcceptedSend, files: DecodedAttachment[]): QueuedSend => {
    const { attachments, ...rest } = send
    return attachments === undefined ? rest : { ...rest, attachments: attachmentMetadata(files) }
}

export const acceptedSendEmailFields = (
    send: QueuedSend | undefined
): Partial<CyclotronInvocationQueueParametersEmailType> => ({
    ...(send?.content && {
        subject: send.content.subject,
        html: send.content.html ?? '',
        text: send.content.text ?? '',
        preheader: '',
    }),
    ...(send?.from && { from: { ...send.from } }),
    ...(send?.replyTo && { replyTo: send.replyTo.join(', ') }),
    ...(send?.cc && { cc: send.cc.join(', ') }),
    ...(send?.bcc && { bcc: send.bcc.join(', ') }),
    ...(send?.attachments && { attachments: send.attachments.map((file) => ({ ...file })) }),
})

// What Django sends to run a transactional email's workflow once.
export const TransactionalEmailRequestSchema = z.object({
    to: z.string().email({ pattern: RECIPIENT_ADDRESS_PATTERN }),
    // The person the send is tracked against. Django falls back to the recipient's address.
    distinct_id: z.string().min(1),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
    // The caller's `Idempotency-Key`. A repeat with the same key and request returns the first send.
    idempotency_key: z.string().min(1).max(255).optional(),
})

export const TEMPLATE_SEND_TOKEN_CLAIMS = { kind: undefined }
export const CODE_SEND_TOKEN_CLAIMS = { kind: 'code_send' }

export const AcceptedSendRequestSchema = TransactionalEmailRequestSchema.extend({ send: AcceptedSendSchema })

export type TransactionalEmailRequest = z.infer<typeof TransactionalEmailRequestSchema> & { send?: AcceptedSend }

export const transactionalEmailRecipients = ({ to, send }: TransactionalEmailRequest): string[] => [
    to,
    ...(send?.cc ?? []),
    ...(send?.bcc ?? []),
]

export const isRecipientFormatIssue = (issue: z.core.$ZodIssue): boolean =>
    issue.code === 'invalid_format' &&
    (issue.path[0] === 'to' || (issue.path[0] === 'send' && (issue.path[1] === 'cc' || issue.path[1] === 'bcc')))

export type TransactionalEmailOutcome =
    | 'queued'
    | 'replayed'
    | 'idempotency_key_in_flight'
    | 'idempotency_key_reused'
    | 'idempotency_unavailable'
    | 'not_configured'
    | 'unauthorized'
    | 'invalid_request'
    | 'not_found'
    | 'not_sendable'
    | 'quota_limited'
    | 'sending_suspended'
    | 'sending_paused'
    | 'recipient_suppressed'
    | 'recipient_unreachable'
    | 'error'

export const transactionalEmailRequestsTotal = new Counter({
    name: 'cdp_transactional_email_requests_total',
    help: 'Requests from Django to run a transactional email, by outcome. Every outcome except `queued` means this request queued no email.',
    labelNames: ['outcome'],
})

export const TRANSACTIONAL_EMAIL_STAGES = [
    'auth',
    'validate',
    'load',
    'build',
    'idempotency',
    'checks',
    'files',
    'queue_insert',
    'metrics_flush',
] as const
export type TransactionalEmailStage = (typeof TRANSACTIONAL_EMAIL_STAGES)[number]

export const transactionalEmailStageDurationMs = new Histogram({
    name: 'cdp_transactional_email_stage_duration_ms',
    help: 'Milliseconds one transactional email request spends in each stage: auth (the JWT), validate (the body), load (the team and the workflow), build (the run and its idempotency fingerprint), idempotency (every Idempotency-Key call to Valkey), checks (suspension, pause, suppression, quota and MX), files (the attachment rows written to the Cyclotron database), queue_insert (the email queue insert), metrics_flush (the hand-off of the result and status rows to the Kafka producer, without the wait for the broker), and total. A request records only the stages it reached, so a refusal shows in the stage that refused it.',
    labelNames: ['stage'],
    buckets: [1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000],
})

// The stages of a request run back to back, so starting a stage ends the one before it. finish() records each stage
// once, with its summed time, so a stage entered twice (idempotency) still counts as one observation per request.
export class TransactionalEmailStageTimer {
    private readonly startedAt = performance.now()
    private current: { stage: TransactionalEmailStage; startedAt: number } | null = null
    private readonly durations = new Map<TransactionalEmailStage, number>()

    start(stage: TransactionalEmailStage): void {
        const now = performance.now()
        this.endCurrent(now)
        this.current = { stage, startedAt: now }
    }

    finish(): void {
        const now = performance.now()
        this.endCurrent(now)
        for (const [stage, durationMs] of this.durations) {
            transactionalEmailStageDurationMs.labels({ stage }).observe(durationMs)
        }
        transactionalEmailStageDurationMs.labels({ stage: 'total' }).observe(now - this.startedAt)
    }

    private endCurrent(now: number): void {
        if (this.current) {
            const { stage, startedAt } = this.current
            this.durations.set(stage, (this.durations.get(stage) ?? 0) + now - startedAt)
            this.current = null
        }
    }
}
