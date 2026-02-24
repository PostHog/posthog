import { HogExecutorServiceHub } from './services/hog-executor.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobalsWithInputs,
    MinimalLogEntry,
} from './types'

export type AsyncFunctionContext = {
    invocation: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>['invocation']
    globals: HogFunctionInvocationGlobalsWithInputs
    hub: HogExecutorServiceHub
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
