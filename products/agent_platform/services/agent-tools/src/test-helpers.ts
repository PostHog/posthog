import { HttpClient, ToolContext } from '@posthog/agent-shared'

const DEFAULT_POSTHOG_API_BASE_URL = 'http://localhost:8010'

export function makeCtx(overrides?: Partial<ToolContext>): ToolContext {
    const logs: Array<{ level: string; msg: string; meta?: Record<string, unknown> }> = []
    return {
        teamId: 1,
        applicationId: 'test-app',
        sessionId: 'test-session',
        secret: (_name: string) => undefined,
        secretAllowedHosts: (_name: string) => undefined,
        log: (level, msg, meta) => {
            logs.push({ level, msg, meta })
        },
        http: new HttpClient(),
        posthogApiBaseUrl: DEFAULT_POSTHOG_API_BASE_URL,
        ...overrides,
    }
}

/** Capture logs into a mutable array attached to the returned ctx. */
export function makeCapturingCtx(): {
    ctx: ToolContext
    logs: Array<{ level: string; msg: string; meta?: Record<string, unknown> }>
} {
    const logs: Array<{ level: string; msg: string; meta?: Record<string, unknown> }> = []
    const ctx: ToolContext = {
        teamId: 1,
        applicationId: 'test-app',
        sessionId: 'test-session',
        secret: () => undefined,
        secretAllowedHosts: () => undefined,
        log: (level, msg, meta) => {
            logs.push({ level, msg, meta })
        },
        http: new HttpClient(),
        posthogApiBaseUrl: DEFAULT_POSTHOG_API_BASE_URL,
    }
    return { ctx, logs }
}
