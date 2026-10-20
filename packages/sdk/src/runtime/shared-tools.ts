import type { JsonValue, ResponseMeta } from '../types.js'

export interface SharedToolSessionOptions {
    baseUrl: string
    publicBaseUrl: string
    token?: string
    organizationId?: string
    taskId?: string
    pinnedProjectId?: number
    getProjectId(signal: AbortSignal): Promise<number>
    setContext(context: { projectId?: number; organizationId?: string }): void
    fetch(url: string, init: RequestInit, signal: AbortSignal): Promise<Response>
    feedback?: (properties: Record<string, JsonValue>) => Promise<void>
}

export interface SharedToolSession {
    execute(toolName: string, input: unknown, signal: AbortSignal): Promise<{ data: JsonValue; meta: ResponseMeta }>
}
