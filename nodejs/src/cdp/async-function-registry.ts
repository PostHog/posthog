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
