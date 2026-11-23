import { Counter, Histogram } from 'prom-client'
import { z } from 'zod'

import {
    CyclotronInvocationQueueParametersEmailType,
    EmailAttachmentMetadata,
    MAX_EMAIL_ATTACHMENTS,
} from '~/cdp/schema/cyclotron'
import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { SHA256_HEX } from '~/cdp/services/messaging/attachment-store'
import { decodeLiquidTags } from '~/cdp/utils/liquid'

import { clickableHrefs, hasReplaceableUnsubscribeLink, isTooLargeToCheck } from '../messaging/helpers/clickable-links'

export const MAX_COPY_RECIPIENTS = 10
export const ATTACHMENT_FILENAME_MAX_LENGTH = 255
export const ATTACHMENT_CONTENT_TYPE_MAX_LENGTH = 78
export const ATTACHMENT_CONTENT_ID_MAX_LENGTH = 78

export const RECIPIENT_ADDRESS_PATTERN =
    /^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/

const CopyRecipientsSchema = z
    .array(z.string().email({ pattern: RECIPIENT_ADDRESS_PATTERN }))
    .max(MAX_COPY_RECIPIENTS)
    .readonly()
    .optional()

const SendCategoryFields = {
    id: z.guid(),
    type: z.enum(['marketing', 'transactional']),
}

const SendCategorySchema = z.object(SendCategoryFields).strict().readonly()

const AcceptedSendCategorySchema = z
    .object({
        ...SendCategoryFields,
        inherited: z.boolean().optional(),
    })
    .strict()
    .readonly()

export type SendCategory = z.infer<typeof SendCategorySchema>
export type AcceptedSendCategory = z.infer<typeof AcceptedSendCategorySchema>

export const SES_UNSUPPORTED_ATTACHMENT_EXTENSIONS: ReadonlySet<string> = new Set([
    '.ade',
    '.adp',
    '.app',
    '.asp',
    '.bas',
    '.bat',
    '.cer',
    '.chm',
    '.cmd',
    '.com',
    '.cpl',
    '.crt',
    '.csh',
    '.der',
    '.exe',
    '.fxp',
    '.gadget',
    '.hlp',
    '.hta',
    '.inf',
    '.ins',
    '.isp',
    '.its',
    '.js',
    '.jse',
    '.ksh',
    '.lib',
    '.lnk',
    '.mad',
    '.maf',
    '.mag',
    '.mam',
    '.maq',
    '.mar',
    '.mas',
    '.mat',
    '.mau',
    '.mav',
    '.maw',
    '.mda',
    '.mdb',
    '.mde',
    '.mdt',
    '.mdw',
    '.mdz',
    '.msc',
    '.msh',
    '.msh1',
    '.msh2',
    '.mshxml',
    '.msh1xml',
    '.msh2xml',
    '.msi',
    '.msp',
    '.mst',
    '.ops',
    '.pcd',
    '.pif',
    '.plg',
    '.prf',
    '.prg',
    '.reg',
    '.scf',
    '.scr',
    '.sct',
    '.shb',
    '.shs',
    '.sys',
    '.ps1',
    '.ps1xml',
    '.ps2',
    '.ps2xml',
    '.psc1',
    '.psc2',
    '.tmp',
    '.url',
    '.vb',
    '.vbe',
    '.vbs',
    '.vps',
    '.vsmacros',
    '.vss',
    '.vst',
    '.vsw',
    '.vxd',
    '.ws',
    '.wsc',
    '.wsf',
    '.wsh',
    '.xnk',
])

const lastExtension = (filename: string): string => {
    const dot = filename.lastIndexOf('.')
    return dot === -1 ? '' : filename.slice(dot).toLowerCase()
}

const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/
const withoutControlCharacters = (field: string) =>
    [
        (value: string) => !CONTROL_CHARACTERS.test(value),
        { message: `${field} cannot contain control characters` },
    ] as const

const attachmentHeaderValue = (field: string, maxLength: number) => {
    const message = `${field} needs 1 to ${maxLength} characters`
    return z
        .string()
        .min(1, { message })
        .max(maxLength, { message })
        .refine(...withoutControlCharacters(field))
        .optional()
}

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
        sensitive: z.boolean().optional(),
        tracking: z
            .object({
                captureEngagement: z.boolean(),
                opens: z.literal(false).optional(),
                clicks: z.boolean().optional(),
            })
            .strict()
            .readonly()
            .refine((tracking) => !(tracking.opens === false && tracking.clicks === true), {
                message: 'click tracking needs open tracking',
            }),
        attachments: z
            .array(
                z
                    .object({
                        sha256: z.string().regex(SHA256_HEX),
                        filename: z
                            .string()
                            .min(1)
                            .max(ATTACHMENT_FILENAME_MAX_LENGTH, {
                                message: `filename can be at most ${ATTACHMENT_FILENAME_MAX_LENGTH} characters`,
                            })
                            .refine(...withoutControlCharacters('filename'))
                            .refine((filename) => !SES_UNSUPPORTED_ATTACHMENT_EXTENSIONS.has(lastExtension(filename)), {
                                error: (issue) => {
                                    const filename = String(issue.input)
                                    return `SES does not send ${lastExtension(filename)} files, so ${filename} cannot be attached`
                                },
                            }),
                        content_type: attachmentHeaderValue('content_type', ATTACHMENT_CONTENT_TYPE_MAX_LENGTH),
                        content_id: attachmentHeaderValue('content_id', ATTACHMENT_CONTENT_ID_MAX_LENGTH),
                    })
                    .strict()
                    .readonly()
            )
            .max(MAX_EMAIL_ATTACHMENTS)
            .readonly()
            .optional(),
        message_category: AcceptedSendCategorySchema.optional(),
    })
    .strict()
    .readonly()

export type AcceptedSend = Omit<z.infer<typeof AcceptedSendSchema>, 'message_category'>

export type QueuedSend = Omit<AcceptedSend, 'attachments'> & { attachments?: readonly EmailAttachmentMetadata[] }

type EmailStep = Extract<HogFlowAction, { type: 'function_email' }>

export const emailStepForApiSend = <Action extends HogFlowAction>(
    action: Action,
    category: SendCategory | undefined
): Action => {
    if (action.type !== 'function_email' || !category) {
        return action
    }
    const step: EmailStep = {
        ...action,
        config: {
            ...action.config,
            message_category_type: category.type,
            message_category_id: category.id,
            skip_frequency_cap: true,
        },
    }
    return step as Action
}

export const hogFlowForApiSend = (hogFlow: HogFlow, category: SendCategory | undefined): HogFlow =>
    category ? { ...hogFlow, actions: hogFlow.actions.map((action) => emailStepForApiSend(action, category)) } : hogFlow

const isMarketingEmailStep = (action: HogFlowAction): action is EmailStep =>
    action.type === 'function_email' && action.config.message_category_type !== 'transactional'

export const marketingEmailStep = (hogFlow: HogFlow, category: SendCategory | undefined): EmailStep | undefined =>
    category?.type === 'marketing' ? hogFlow.actions.find(isMarketingEmailStep) : undefined

const LIQUID_UNSUBSCRIBE_EXPRESSION =
    '(?:\\{\\{-?\\s*unsubscribe_url(?:_one_click)?\\s*(?:-?|\\|\\s*[a-zA-Z_][^{}]*)\\}\\}|\\{%-?\\s*unsubscribe_url\\s*-?%\\})'
const LIQUID_UNSUBSCRIBE_PLACEHOLDER = new RegExp(LIQUID_UNSUBSCRIBE_EXPRESSION)
const LIQUID_UNSUBSCRIBE_BASE = new RegExp(`^${LIQUID_UNSUBSCRIBE_EXPRESSION}$`)
const LIQUID_UNSUBSCRIBE_WITH_SUFFIX = new RegExp(`^${LIQUID_UNSUBSCRIBE_EXPRESSION}[?#][^\\r\\n]*$`)
const LIQUID_UNSUBSCRIBE_HREF = new RegExp(`^${LIQUID_UNSUBSCRIBE_EXPRESSION}(?:[?#][^\\r\\n]*)?$`)
const LIQUID_QUERY_SUFFIX = /^[?#][^\r\n]*$/
const LIQUID_CONTROL_KEYWORD = /^-?\s*(if|unless|case|elsif|when|else|endif|endunless|endcase)(?=\s|-?$)/

type LiquidBranchState = 'empty' | 'matched_base' | 'matched_query' | 'invalid'

type LiquidFrame = {
    openTag: 'root' | 'if' | 'unless' | 'case'
    mode: 'href' | 'suffix'
    initialQuery: boolean
    inActiveBranch: boolean
    seenElse: boolean
    matchedState: 'none' | 'matched_base' | 'matched_query'
    allBranchesValid: boolean
    allBranchesQuery: boolean
    branchState: LiquidBranchState
    branchText: string
}

const isLiquidUnsubscribeHref = (rawHref: string): boolean => {
    const href = decodeLiquidTags(rawHref).trim()
    if (LIQUID_UNSUBSCRIBE_HREF.test(href)) {
        return true
    }
    if (!href.includes('{%')) {
        return false
    }

    const root: LiquidFrame = {
        openTag: 'root',
        mode: 'href',
        initialQuery: false,
        inActiveBranch: true,
        seenElse: false,
        matchedState: 'none',
        allBranchesValid: true,
        allBranchesQuery: false,
        branchState: 'empty',
        branchText: '',
    }
    const stack: LiquidFrame[] = [root]

    const flushText = (frame: LiquidFrame): void => {
        const text = frame.branchText.trim()
        frame.branchText = ''
        if (!text || !frame.inActiveBranch || frame.branchState === 'invalid') {
            return
        }
        if (frame.branchState === 'empty') {
            if (LIQUID_UNSUBSCRIBE_BASE.test(text)) {
                frame.branchState = 'matched_base'
            } else if (LIQUID_UNSUBSCRIBE_WITH_SUFFIX.test(text)) {
                frame.branchState = 'matched_query'
            } else {
                frame.branchState = 'invalid'
            }
        } else if (frame.branchState === 'matched_base') {
            frame.branchState = LIQUID_QUERY_SUFFIX.test(text) ? 'matched_query' : 'invalid'
        } else if (/[\r\n]/.test(text)) {
            frame.branchState = 'invalid'
        }
    }

    const finalizeBranch = (frame: LiquidFrame): void => {
        flushText(frame)
        if (frame.inActiveBranch) {
            if (frame.mode === 'href') {
                if (frame.branchState === 'matched_base') {
                    frame.matchedState = 'matched_base'
                } else if (frame.branchState === 'matched_query' && frame.matchedState === 'none') {
                    frame.matchedState = 'matched_query'
                }
            } else {
                if (frame.branchState === 'invalid') {
                    frame.allBranchesValid = false
                }
                if (frame.branchState !== 'matched_query') {
                    frame.allBranchesQuery = false
                }
            }
        }
        frame.branchState = frame.mode === 'suffix' ? (frame.initialQuery ? 'matched_query' : 'matched_base') : 'empty'
    }

    let pos = 0
    while (pos < href.length) {
        const open = href.indexOf('{%', pos)
        if (open === -1) {
            stack[stack.length - 1].branchText += href.slice(pos)
            break
        }
        const close = href.indexOf('%}', open + 2)
        if (close === -1) {
            return false
        }
        const inner = href.slice(open + 2, close)
        const keywordMatch = inner.match(LIQUID_CONTROL_KEYWORD)
        if (!keywordMatch) {
            stack[stack.length - 1].branchText += href.slice(pos, close + 2)
            pos = close + 2
            continue
        }
        const current = stack[stack.length - 1]
        current.branchText += href.slice(pos, open)
        const keyword = keywordMatch[1]
        if (keyword === 'if' || keyword === 'unless' || keyword === 'case') {
            flushText(current)
            const isSuffix =
                current.inActiveBranch &&
                (current.branchState === 'matched_base' || current.branchState === 'matched_query')
            const initialQuery = isSuffix && current.branchState === 'matched_query'
            stack.push({
                openTag: keyword,
                mode: isSuffix ? 'suffix' : 'href',
                initialQuery,
                inActiveBranch: keyword !== 'case',
                seenElse: false,
                matchedState: 'none',
                allBranchesValid: true,
                allBranchesQuery: true,
                branchState: isSuffix ? (initialQuery ? 'matched_query' : 'matched_base') : 'empty',
                branchText: '',
            })
        } else if (keyword === 'elsif' || keyword === 'when' || keyword === 'else') {
            if (current.openTag === 'root' || current.seenElse) {
                return false
            }
            if (
                (keyword === 'elsif' && current.openTag !== 'if') ||
                (keyword === 'when' && current.openTag !== 'case')
            ) {
                return false
            }
            finalizeBranch(current)
            current.inActiveBranch = true
            if (keyword === 'else') {
                current.seenElse = true
            }
        } else {
            if (current.openTag === 'root' || keyword !== `end${current.openTag}`) {
                return false
            }
            stack.pop()
            finalizeBranch(current)
            const parent = stack[stack.length - 1]
            if (parent.inActiveBranch && parent.branchState !== 'invalid') {
                if (current.mode === 'href') {
                    parent.branchState =
                        parent.branchState === 'empty' && current.matchedState !== 'none'
                            ? current.matchedState
                            : 'invalid'
                } else if (!current.allBranchesValid) {
                    parent.branchState = 'invalid'
                } else if (current.initialQuery || (current.seenElse && current.allBranchesQuery)) {
                    parent.branchState = 'matched_query'
                }
            }
        }
        pos = close + 2
    }

    if (stack.length !== 1) {
        return false
    }
    flushText(root)
    return root.branchState === 'matched_base' || root.branchState === 'matched_query'
}

const hasLiquidUnsubscribeLink = ({ html, text }: { html?: string; text?: string }): boolean =>
    html
        ? clickableHrefs(html).some(isLiquidUnsubscribeHref)
        : LIQUID_UNSUBSCRIBE_PLACEHOLDER.test(decodeLiquidTags(text ?? ''))

const hasAddresses = (value: unknown): boolean =>
    Array.isArray(value) ? value.length > 0 : typeof value === 'string' && value.trim() !== ''

const marketingEmailInputs = (action: HogFlowAction, category: SendCategory | undefined) =>
    category?.type === 'marketing' && isMarketingEmailStep(action)
        ? (action.config.inputs.email?.value ?? {})
        : undefined

export type MarketingSendRefusal = 'content_too_large' | 'unsubscribe_link_required' | 'copies_not_allowed'

export const marketingCopiesRefusal = (
    action: HogFlowAction,
    send: AcceptedSend | undefined,
    category: SendCategory | undefined
): 'copies_not_allowed' | undefined => {
    const email = marketingEmailInputs(action, category)
    return email && (hasAddresses(send?.cc ?? email.cc) || hasAddresses(send?.bcc ?? email.bcc))
        ? 'copies_not_allowed'
        : undefined
}

export const marketingSendRefusal = (
    action: HogFlowAction,
    send: AcceptedSend | undefined,
    category: SendCategory | undefined
): MarketingSendRefusal | undefined => {
    const email = marketingEmailInputs(action, category)
    if (!email) {
        return undefined
    }
    if (isTooLargeToCheck(send?.content ?? email)) {
        return 'content_too_large'
    }
    const linked = send?.content ? hasReplaceableUnsubscribeLink(send.content) : hasLiquidUnsubscribeLink(email)
    return linked ? marketingCopiesRefusal(action, send, category) : 'unsubscribe_link_required'
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

const ScheduledAtSchema = z.string().datetime({ offset: true })

export const RescheduleRequestSchema = z.object({ scheduled_at: ScheduledAtSchema })

// What Django sends to run a transactional email's workflow once.
export const TransactionalEmailRequestSchema = z.object({
    to: z.string().email({ pattern: RECIPIENT_ADDRESS_PATTERN }),
    // The person the send is tracked against. Django falls back to the recipient's address.
    distinct_id: z.string().min(1),
    // The caller's `message_data`, available to the template as `variables`.
    variables: z.record(z.string(), z.any()).default({}),
    // The caller's `Idempotency-Key`. A repeat with the same key and request returns the first send.
    idempotency_key: z.string().min(1).max(255).optional(),
    scheduled_at: ScheduledAtSchema.optional(),
})

export const TEMPLATE_SEND_TOKEN_CLAIMS = { kind: undefined }
export const CODE_SEND_TOKEN_CLAIMS = { kind: 'code_send' }
export const ATTACHMENT_UPLOAD_TOKEN_CLAIMS = { kind: 'attachment_upload' }

export const AcceptedSendRequestSchema = TransactionalEmailRequestSchema.extend({ send: AcceptedSendSchema }).transform(
    ({ send: { message_category, ...send }, ...request }) => ({ ...request, send, message_category })
)

export type TransactionalEmailRequest = z.infer<typeof TransactionalEmailRequestSchema> & {
    send?: AcceptedSend
    message_category?: AcceptedSendCategory
}

export const transactionalEmailRecipients = ({ to, send }: TransactionalEmailRequest): string[] => [
    to,
    ...(send?.cc ?? []),
    ...(send?.bcc ?? []),
]

export const isRecipientFormatIssue = (issue: z.core.$ZodIssue): boolean =>
    issue.code === 'invalid_format' &&
    (issue.path[0] === 'to' || (issue.path[0] === 'send' && (issue.path[1] === 'cc' || issue.path[1] === 'bcc')))

export type TransactionalSendRefusal =
    | 'idempotency_key_reused'
    | 'idempotency_unavailable'
    | 'intake_unavailable'
    | 'invalid_request'
    | 'not_sendable'
    | 'quota_limited'
    | 'sending_suspended'
    | 'sending_paused'
    | 'recipient_suppressed'
    | 'recipient_opted_out'
    | MarketingSendRefusal
    | 'recipient_unreachable'
    | 'invalid_scheduled_at'
    | 'sandbox_recipient_not_member'
    | 'sandbox_fields_unsupported'
    | 'sandbox_sender_unavailable'

export type TransactionalEmailOutcome =
    | 'queued'
    | 'replayed'
    | TransactionalSendRefusal
    | 'not_configured'
    | 'unauthorized'
    | 'invalid_request'
    | 'not_found'
    | 'field_not_accepted'
    | 'workflow_can_wait'
    | 'workflow_shape_not_supported'
    | 'attachment_not_uploaded'
    | 'message_too_large'
    | 'email_render_limit_exceeded'
    | 'utm_value_too_long'
    | 'email_body_too_many_tags'
    | 'delivery_unavailable'
    | 'error'

export const transactionalEmailRequestsTotal = new Counter({
    name: 'cdp_transactional_email_requests_total',
    help: 'Answers to Django for a transactional email, by outcome and route: `single` counts a request, `batch` counts each recipient of a batch. It records the answer, not the delivery: after `intake_unavailable` or `error`, the email may still go out.',
    labelNames: ['outcome', 'route'],
})

export const TRANSACTIONAL_EMAIL_STAGES = [
    'auth',
    'validate',
    'load',
    'build',
    'idempotency',
    'checks',
    'attachments',
    'queue_insert',
    'intake_produce',
    'metrics_flush',
] as const
export type TransactionalEmailStage = (typeof TRANSACTIONAL_EMAIL_STAGES)[number]

export const transactionalEmailStageDurationMs = new Histogram({
    name: 'cdp_transactional_email_stage_duration_ms',
    help: 'Milliseconds one transactional email request, or one batch (route `batch`), spends in each stage: auth (the JWT), validate (the body), load (the team and the workflow), build (the run and its idempotency fingerprint), idempotency (every Idempotency-Key call to Valkey), checks (suspension, pause, suppression, opt-out, quota and MX), attachments (verifying the files and estimating the message, only for a send with files), queue_insert (the email queue insert), intake_produce (the produce to the intake topic and the wait for its ack, in intake async mode), metrics_flush (the hand-off of the result and status rows to the Kafka producer, without the wait for the broker), and total. A request records only the stages it reached, so a refusal shows in the stage that refused it.',
    labelNames: ['stage', 'route'],
    buckets: [1, 2.5, 5, 10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000],
})

export type TransactionalEmailRoute = 'single' | 'batch'

// The stages of a request run back to back, so starting a stage ends the one before it. finish() records each stage
// once, with its summed time, so a stage entered twice (idempotency) still counts as one observation per request.
export class TransactionalEmailStageTimer {
    private readonly startedAt = performance.now()
    private current: { stage: TransactionalEmailStage; startedAt: number } | null = null
    private readonly durations = new Map<TransactionalEmailStage, number>()

    constructor(private readonly route: TransactionalEmailRoute = 'single') {}

    start(stage: TransactionalEmailStage): void {
        const now = performance.now()
        this.endCurrent(now)
        this.current = { stage, startedAt: now }
    }

    finish(): void {
        const now = performance.now()
        this.endCurrent(now)
        for (const [stage, durationMs] of this.durations) {
            transactionalEmailStageDurationMs.labels({ stage, route: this.route }).observe(durationMs)
        }
        transactionalEmailStageDurationMs.labels({ stage: 'total', route: this.route }).observe(now - this.startedAt)
    }

    private endCurrent(now: number): void {
        if (this.current) {
            const { stage, startedAt } = this.current
            this.durations.set(stage, (this.durations.get(stage) ?? 0) + now - startedAt)
            this.current = null
        }
    }
}
