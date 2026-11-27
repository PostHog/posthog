/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

/**
 * Step 1 of the upload: returns a presigned POST to send the transcript file to. The file goes straight to storage. Call complete_upload once the POST succeeds.
 */
export const agentTranscriptsStartUploadCreateBodyFilenameMax = 255

export const AgentTranscriptsStartUploadCreateBody = /* @__PURE__ */ zod.object({
    filename: zod
        .string()
        .max(agentTranscriptsStartUploadCreateBodyFilenameMax)
        .describe('Name of the transcript file. It must end in .jsonl, .json, .md or .txt.'),
    size_bytes: zod.number().describe('Size of the transcript file in bytes, at most 25 MB.'),
    agent: zod
        .enum(['claude_code', 'codex', 'cursor', 'claude_app', 'chatgpt', 'other'])
        .describe(
            '\* `claude_code` - Claude Code\n\* `codex` - Codex\n\* `cursor` - Cursor\n\* `claude_app` - Claude app\n\* `chatgpt` - ChatGPT\n\* `other` - Other'
        )
        .describe(
            'The AI agent the transcript comes from.\n\n\* `claude_code` - Claude Code\n\* `codex` - Codex\n\* `cursor` - Cursor\n\* `claude_app` - Claude app\n\* `chatgpt` - ChatGPT\n\* `other` - Other'
        ),
})
