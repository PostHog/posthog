import { newHogCallable, newHogClosure, printHogStringOutput, VMState } from '@posthog/hogvm'
import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import { execHogAsync } from 'lib/hog'

import { performQuery } from '~/queries/query'
import { HogQLQuery, NodeKind } from '~/queries/schema'

import type { hogReplLogicType } from './hogReplLogicType'

export interface ReplChunk {
    code: string
    result?: string
    print?: string
    error?: string
    bytecode?: any[]
    locals?: any[]
    state?: any
    status: 'pending' | 'success' | 'error'
}

export const hogReplLogic = kea<hogReplLogicType>([
    path(['scenes', 'debug', 'HogRepl']),
    actions({
        runCode: (code: string) => ({ code }),
        setResult: (index: number, result?: string, error?: string) => ({ index, result, error }),
        print: (index: number, line?: string) => ({ index, line }),
        setBytecode: (index: number, bytecode: any[], locals: any[]) => ({ index, bytecode, locals }),
        setVMState: (index: number, state: any) => ({ index, state }),
        setCurrentCode: (code: string) => ({ code }),
        runCurrentCode: true,
        editFromHere: (index: number) => ({ index }),
        setReplChunks: (replChunks: ReplChunk[]) => ({ replChunks }),
    }),
    reducers({
        currentCode: ['', { setCurrentCode: (_, { code }) => code }],
        replChunks: [
            [] as ReplChunk[],
            {
                setReplChunks: (_, { replChunks }) => replChunks,
                runCode: (state, { code }) => [...state, { code, status: 'pending' } as ReplChunk],
                setResult: (state, { index, result, error }) =>
                    state.map((chunk, i) =>
                        i === index ? { ...chunk, result, error, status: error ? 'error' : 'success' } : chunk
                    ),
                setBytecode: (state, { index, bytecode, locals }) =>
                    state.map((chunk, i) => (i === index ? { ...chunk, bytecode, locals } : chunk)),
                print: (state, { index, line }) =>
                    state.map((chunk, i) =>
                        i === index ? { ...chunk, print: (chunk.print ? chunk.print + '\n' : '') + line } : chunk
                    ),
                setVMState: (state, { index, state: vmState }) =>
                    state.map((chunk, i) => (i === index ? { ...chunk, state: vmState } : chunk)),
            },
        ],
    }),
    selectors({
        lastLocals: [
            (s) => [s.replChunks],
            (replChunks): ReplChunk['locals'] | undefined => {
                for (let i = replChunks.length - 1; i >= 0; i--) {
                    if (replChunks[i].locals) {
                        return replChunks[i].locals
                    }
                }
                return undefined
            },
        ],
        lastState: [
            (s) => [s.replChunks],
            (replChunks): VMState | undefined => {
                for (let i = replChunks.length - 1; i >= 0; i--) {
                    if (replChunks[i].state) {
                        return replChunks[i].state
                    }
                }
                return undefined
            },
        ],
        lastLocalGlobals: [
            (s) => [s.lastLocals],
            (lastLocals): Record<string, any> | undefined => {
                if (lastLocals) {
                    return lastLocals.reduce((acc, local) => ({ ...acc, [local[0]]: 'local' }), {})
                }
                return undefined
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        editFromHere: ({ index }) => {
            actions.setCurrentCode(
                [...values.replChunks.slice(index).map((chunk) => chunk.code), values.currentCode].join('\n')
            )
            actions.setReplChunks(values.replChunks.slice(0, index))
        },
        runCode: async ({ code }) => {
            const options = {
                asyncFunctions: {
                    sleep: async (ms: number) => {
                        await new Promise((resolve) => setTimeout(resolve, ms))
                    },
                    fetch: async ([url, fetchOptions]: [string | undefined, Record<string, any> | undefined]) => {
                        if (typeof url !== 'string') {
                            throw new Error('fetch: Invalid URL')
                        }

                        const method = fetchOptions?.method || 'POST'
                        const headers = fetchOptions?.headers || {
                            'Content-Type': 'application/json',
                        }
                        // Modify the body to ensure it is a string (we allow Hog to send an object to keep things simple)
                        const body: string | undefined = fetchOptions?.body
                            ? typeof fetchOptions.body === 'string'
                                ? fetchOptions.body
                                : JSON.stringify(fetchOptions.body)
                            : fetchOptions?.body

                        const result = await fetch(url, {
                            method,
                            headers,
                            body,
                        })
                        const response = {
                            status: result.status,
                            body: await result.text(),
                        }
                        if (result.headers.get('content-type')?.includes('application/json')) {
                            try {
                                response.body = JSON.parse(response.body)
                            } catch (e) {
                                console.error('Failed to parse JSON response', e)
                            }
                        }
                        return response
                    },
                    run: async (queryString: string) => {
                        const hogQLQuery: HogQLQuery = { kind: NodeKind.HogQLQuery, query: queryString }
                        const response = await performQuery(hogQLQuery)
                        return { results: response.results, columns: response.columns }
                    },
                },
                functions: {
                    print: (value: any) => {
                        actions.print(index, printHogStringOutput(value))
                    },
                },
            }
            const index = values.replChunks.length - 1
            const { lastLocals, lastState } = values

            try {
                const res = await api.hog.create(code, lastLocals)
                const [_h, version, ...bytecode] = res.bytecode
                const locals = res.locals
                actions.setBytecode(index, bytecode, locals)

                const nextBytecode = [_h, version]
                for (const replChunk of values.replChunks) {
                    if (replChunk.bytecode) {
                        nextBytecode.push(...replChunk.bytecode)
                    }
                }
                const ip = nextBytecode.length - bytecode.length
                if (nextBytecode[nextBytecode.length - 1] === 35) {
                    nextBytecode.pop()
                }
                const nextStack = [...(lastState?.stack ?? [])]
                if (nextStack.length !== lastLocals?.length) {
                    nextStack.splice(lastLocals?.length ?? 0)
                }
                const state: VMState = {
                    stack: nextStack ?? [],
                    bytecode: nextBytecode,
                    callStack: [
                        {
                            ip: ip,
                            chunk: 'root',
                            stackStart: 0,
                            argCount: 0,
                            closure: newHogClosure(
                                newHogCallable('main', {
                                    name: '',
                                    argCount: 0,
                                    upvalueCount: 0,
                                    ip: ip,
                                    chunk: 'root',
                                })
                            ),
                        },
                    ],
                    upvalues: lastState?.upvalues ?? [],
                    ops: lastState?.ops ?? 0,
                    asyncSteps: lastState?.asyncSteps ?? 0,
                    declaredFunctions: lastState?.declaredFunctions ?? {},
                    throwStack: lastState?.throwStack ?? [],
                    maxMemUsed: lastState?.maxMemUsed ?? 0,
                    syncDuration: lastState?.syncDuration ?? 0,
                }
                const result = await execHogAsync(state, options)

                // Set the result
                const response =
                    (result.state?.stack?.length ?? 0) > 0
                        ? result.state?.stack?.[result.state.stack.length - 1]
                        : 'null'
                actions.setResult(index, printHogStringOutput(response))
                actions.setVMState(index, result.state)
            } catch (error: any) {
                // Handle errors
                console.error(error)
                actions.setResult(index, undefined, error.toString())
            }
        },
        runCurrentCode: () => {
            actions.runCode(values.currentCode)
            actions.setCurrentCode('')
        },
    })),
])
