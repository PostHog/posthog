/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `pending_upload` - Pending upload
 * * `submitted` - Submitted
 * * `changes_requested` - Changes requested
 * * `approved` - Approved
 * * `declined` - Declined
 */
export type SubmissionStatusEnumApi = (typeof SubmissionStatusEnumApi)[keyof typeof SubmissionStatusEnumApi]

export const SubmissionStatusEnumApi = {
    PendingUpload: 'pending_upload',
    Submitted: 'submitted',
    ChangesRequested: 'changes_requested',
    Approved: 'approved',
    Declined: 'declined',
} as const

/**
 * * `claude_code` - Claude Code
 * * `codex` - Codex
 * * `cursor` - Cursor
 * * `claude_app` - Claude app
 * * `chatgpt` - ChatGPT
 * * `other` - Other
 */
export type TranscriptAgentEnumApi = (typeof TranscriptAgentEnumApi)[keyof typeof TranscriptAgentEnumApi]

export const TranscriptAgentEnumApi = {
    ClaudeCode: 'claude_code',
    Codex: 'codex',
    Cursor: 'cursor',
    ClaudeApp: 'claude_app',
    Chatgpt: 'chatgpt',
    Other: 'other',
} as const

export interface CustomerSubmissionStateApi {
    /** Where the organization's submission stands. Null when nobody has started an upload.
     *
     * * `pending_upload` - Pending upload
     * * `submitted` - Submitted
     * * `changes_requested` - Changes requested
     * * `approved` - Approved
     * * `declined` - Declined */
    status: SubmissionStatusEnumApi | null
    /** The AI agent the transcript comes from, as the submitter chose it.
     *
     * * `claude_code` - Claude Code
     * * `codex` - Codex
     * * `cursor` - Cursor
     * * `claude_app` - Claude app
     * * `chatgpt` - ChatGPT
     * * `other` - Other */
    agent: TranscriptAgentEnumApi | null
    /**
     * Name of the uploaded transcript file.
     * @nullable
     */
    original_filename: string | null
    /**
     * When the last upload passed validation and went to review.
     * @nullable
     */
    submitted_at: string | null
    /**
     * The reviewer's message to the organization. Set when changes are requested or the submission is declined.
     * @nullable
     */
    review_message: string | null
    /** Days after submission that the transcript file is kept before it is deleted. */
    retention_days: number
    /** The largest transcript file accepted, in bytes. */
    max_size_bytes: number
    /** File extensions accepted for a transcript, with the leading dot, for example `.jsonl`. */
    allowed_extensions: string[]
}

export interface AgentTranscriptErrorApi {
    /** The error class, for example `validation_error`. */
    type: string
    /** A stable code for the error, for example `contains_secret`. */
    code: string
    /** What went wrong and what to do next. */
    detail: string
    /**
     * The request field the error is about, if any.
     * @nullable
     */
    attr: string | null
}

export interface StartUploadRequestApi {
    /**
     * Name of the transcript file. It must end in .jsonl, .json, .md or .txt.
     * @maxLength 255
     */
    filename: string
    /** Size of the transcript file in bytes, at most 25 MB. */
    size_bytes: number
    /** The AI agent the transcript comes from.
     *
     * * `claude_code` - Claude Code
     * * `codex` - Codex
     * * `cursor` - Cursor
     * * `claude_app` - Claude app
     * * `chatgpt` - ChatGPT
     * * `other` - Other */
    agent: TranscriptAgentEnumApi
}

/**
 * Form fields to send with the file in the same POST, before the file field.
 */
export type PresignedUploadApiFormFields = { [key: string]: string }

export interface PresignedUploadApi {
    /** POST the file here as multipart/form-data. */
    upload_url: string
    /** Form fields to send with the file in the same POST, before the file field. */
    form_fields: PresignedUploadApiFormFields
    /** Seconds before the upload URL expires. */
    expires_in: number
}
