import { z } from 'zod'

// The host side of the canvas postMessage protocol. It mirrors PostHog Desktop's
// freeformSchemas.ts, because the sandbox document and the built artifact runtime
// speak one protocol to both hosts. A canvas runs untrusted code in an opaque-origin
// iframe, so the schemas below are the allowlist of what it may ask the host to do.

// pinned: protocol channel tag, shared with the sandbox document and the artifact runtime
export const CANVAS_CHANNEL = 'posthog-canvas'

export function isSafePostHogUrl(url: string): boolean {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return false
    }
    return (
        parsed.protocol === 'https:' && (parsed.hostname === 'posthog.com' || parsed.hostname.endsWith('.posthog.com'))
    )
}

export function isSafeGitHubPullRequestUrl(url: string): boolean {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return false
    }
    return (
        parsed.protocol === 'https:' &&
        parsed.hostname === 'github.com' &&
        !parsed.username &&
        !parsed.password &&
        !parsed.port &&
        !parsed.search &&
        /^\/[a-z0-9-]+\/[a-z0-9_.-]+\/pull\/[1-9]\d*(?:\/(?:files|commits|checks))?\/?$/i.test(parsed.pathname)
    )
}

export const canvasConnectorProviderSchema = z.union([
    z.literal('github'),
    z
        .string()
        .max(300)
        .regex(/^mcp:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$/i),
])

export const canvasConnectorCallInputSchema = z.object({
    provider: canvasConnectorProviderSchema,
    tool: z.string().min(1).max(200),
    arguments: z.record(z.string().max(128), z.unknown()).default({}),
    refresh: z.number().int().min(30).max(86_400).optional(),
})
export type CanvasConnectorCallInput = z.infer<typeof canvasConnectorCallInputSchema>

export const canvasAgentRequestInputSchema = z.object({
    prompt: z.string().min(1).max(10_000),
})

export type CanvasTheme = 'light' | 'dark'

// The only navigations a canvas may request. There is no free-form route field, and the
// space is never part of the intent: the host supplies it from the loaded record.
export const canvasNavIntentSchema = z.discriminatedUnion('target', [
    z.object({ target: z.literal('task'), taskId: z.string().min(1) }),
    z.object({ target: z.literal('new-task') }),
    z.object({
        target: z.literal('compose-task'),
        prompt: z.string().max(16_000).optional(),
        repository: z
            .string()
            .max(200)
            .regex(/^[a-z0-9-]+\/[a-z0-9_.-]+$/i)
            .optional(),
    }),
    z.object({ target: z.literal('canvas'), dashboardId: z.string().min(1) }),
    z.object({ target: z.literal('new-canvas') }),
    z.object({ target: z.literal('connect'), provider: canvasConnectorProviderSchema }),
])
export type CanvasNavIntent = z.infer<typeof canvasNavIntentSchema>

export const CANVAS_DATA_METHODS = [
    'query',
    'loadInsight',
    'capture',
    'run',
    'stateGet',
    'stateSet',
    'stateList',
    'actionInvoke',
    'agentRequest',
    'connectorCall',
] as const
export type CanvasDataMethod = (typeof CANVAS_DATA_METHODS)[number]

const canvasTextSelectionSchema = z
    .object({
        quote: z.string(),
        prefix: z.string(),
        suffix: z.string(),
        start: z.number().int().min(0),
        end: z.number().int().min(0),
        rect: z.object({
            top: z.number().finite(),
            right: z.number().finite(),
            bottom: z.number().finite(),
            left: z.number().finite(),
        }),
    })
    .refine(({ start, end }) => end > start)

const channel = z.literal(CANVAS_CHANNEL)

export const canvasToHostMessageSchema = z.discriminatedUnion('type', [
    z.object({ channel, type: z.literal('ready') }),
    z.object({
        channel,
        type: z.literal('data-request'),
        id: z.string().min(1).max(128),
        method: z.enum(CANVAS_DATA_METHODS),
        payload: z.unknown(),
    }),
    z.object({
        channel,
        type: z.literal('error'),
        message: z.string().max(10_000),
        stack: z.string().max(50_000).optional(),
    }),
    z.object({ channel, type: z.literal('rendered') }),
    z.object({ channel, type: z.literal('navigate'), nav: canvasNavIntentSchema }),
    z.object({
        channel,
        type: z.literal('open-external'),
        url: z.string().refine((url) => isSafePostHogUrl(url) || isSafeGitHubPullRequestUrl(url)),
    }),
    z.object({ channel, type: z.literal('text-selection'), selection: canvasTextSelectionSchema }),
    z.object({ channel, type: z.literal('text-selection-cleared') }),
    z.object({ channel, type: z.literal('comment-activate'), id: z.string().min(1).max(128) }),
    z.object({
        channel,
        type: z.literal('keydown'),
        key: z.string().min(1).max(32),
        code: z.string().max(32),
        metaKey: z.boolean(),
        ctrlKey: z.boolean(),
        shiftKey: z.boolean(),
        altKey: z.boolean(),
    }),
])
export type CanvasToHostMessage = z.infer<typeof canvasToHostMessageSchema>

export type HostToCanvasMessage =
    | {
          channel: typeof CANVAS_CHANNEL
          type: 'init'
          files: Record<string, string>
          entry: string
          theme?: CanvasTheme
          highlights?: unknown[]
      }
    | { channel: typeof CANVAS_CHANNEL; type: 'set-theme'; theme: CanvasTheme }
    | { channel: typeof CANVAS_CHANNEL; type: 'set-comment-highlights'; highlights: unknown[] }
    | { channel: typeof CANVAS_CHANNEL; type: 'clear-text-selection' }
    | {
          channel: typeof CANVAS_CHANNEL
          type: 'data-response'
          id: string
          ok: boolean
          result?: unknown
          error?: string
      }
