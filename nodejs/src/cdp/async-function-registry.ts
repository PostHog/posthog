import { TeamManager } from '~/common/utils/team-manager'

import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobalsWithInputs,
    MinimalLogEntry,
} from './types'
import { ScopedServiceJwt } from './utils/scoped-service-jwt'

export type AsyncFunctionContext = {
    invocation: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>['invocation']
    globals: HogFunctionInvocationGlobalsWithInputs
    teamManager: TeamManager
    siteUrl: string
    // In-cluster Django base URL for /api/projects/<team_id>/internal/... routes, which
    // Contour blocks from the public internet. Only first-party handlers may call it.
    internalApiBaseUrl: string
    conversationsTicketsJwt: ScopedServiceJwt
    // Handlers that do real inline I/O without ever setting queueParameters (so the executor's
    // own queued-type counting never sees them, see internal-api-call.ts) must call this once
    // per invocation to share the same per-dequeue async-work budget queued calls are capped by.
    // Throws once the budget is exhausted. A no-op for callers that don't enforce a budget.
    consumeInlineAsyncBudget: () => void
}

export type AsyncFunctionHandler = {
    execute: (
        args: any[],
        context: AsyncFunctionContext,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    ) => Promise<void> | void

    mock: (args: any[], logs: MinimalLogEntry[]) => any
}

const asyncFunctionHandlers = new Map<string, AsyncFunctionHandler>()

export function registerAsyncFunction(name: string, handler: AsyncFunctionHandler): void {
    if (asyncFunctionHandlers.has(name)) {
        throw new Error(`Async function '${name}' is already registered`)
    }
    asyncFunctionHandlers.set(name, handler)
}

export function getAsyncFunctionHandler(name: string): AsyncFunctionHandler | undefined {
    return asyncFunctionHandlers.get(name)
}

export function getRegisteredAsyncFunctionNames(): string[] {
    return Array.from(asyncFunctionHandlers.keys())
}
