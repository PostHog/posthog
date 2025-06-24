import { newHogCallable, newHogClosure, VMState } from '@posthog/hogvm'
import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { execHogAsync } from 'lib/hog'
import { urls } from 'scenes/urls'

import type { hogReplLogicType } from './hogReplLogicType'

export interface ReplChunk {
    code: string
    result?: string
    print?: any[][]
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
        print: (index: number, line: any[]) => ({ index, line }),
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
                        i === index ? { ...chunk, print: [...(chunk.print ?? []), line] } : chunk
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
                    return lastLocals.reduce((acc, local) => Object.assign(acc, { [local[0]]: 'local' }), {})
                }
                return undefined
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        editFromHere: ({ index }) => {
            const code = [...values.replChunks.slice(index).map((chunk) => chunk.code), values.currentCode].join('\n')
            actions.setCurrentCode(code.replace(/\n+$/, ''))
            actions.setReplChunks(values.replChunks.slice(0, index))
        },
        runCode: async ({ code }) => {
            const index = values.replChunks.length - 1
            const { lastLocals, lastState } = values

            try {
                const res = await api.hog.create(code, lastLocals, true)
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
                    bytecodes: { root: { bytecode: nextBytecode } },
                    callStack: [
                        {
                            ip: ip,
                            chunk: 'root',
                            stackStart: 0,
                            argCount: 0,
                            closure: newHogClosure(
                                newHogCallable('local', {
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
                const result = await execHogAsync(state, {
                    repl: true,
                    functions: {
                        print: (...args: any[]) => {
                            actions.print(index, args)
                        },
                    },
                })

                // Show the last stack value if no other result is returned
                const response =
                    result.result !== undefined
                        ? result.result
                        : (result.state?.stack?.length ?? 0) > 0
                        ? result.state?.stack?.[result.state.stack.length - 1]
                        : 'null'
                actions.setResult(index, response)
                actions.setVMState(index, result.state)
            } catch (error: any) {
                // Handle errors
                console.error(error)
                actions.setResult(index, undefined, (error.error || error.message || error).toString())
            }
        },
        runCurrentCode: () => {
            actions.runCode(values.currentCode)
            actions.setCurrentCode('')
        },
    })),
    actionToUrl(({ values }) => {
        const fn = (): [string, undefined, Record<string, any> | undefined, { replace: true }] | undefined => {
            if (values.replChunks.length > 0) {
                // Chrome has a 2MB limit for the HASH params, set ours at 1MB
                const replChunksLength = JSON.stringify(values.replChunks).length
                if (replChunksLength > 1024 * 1024) {
                    // Try with just the code
                    const newCode = values.replChunks.map((chunk) => chunk.code).join('\n')
                    if (newCode.length > 1024 * 1024) {
                        // Still not enough, abort
                        return [urls.debugHog(), undefined, undefined, { replace: true }]
                    }
                    return [urls.debugHog(), undefined, { code: newCode }, { replace: true }]
                }

                return [
                    urls.debugHog(),
                    undefined,
                    { repl: values.replChunks, code: values.currentCode },
                    { replace: true },
                ]
            }
        }

        return {
            setReplChunks: fn,
            runCode: fn,
            setResult: fn,
            setBytecode: fn,
            print: fn,
            setVMState: fn,
            setCurrentCode: fn,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.debugHog()]: (_, __, { repl, code }, { method }) => {
            if (method === 'PUSH' || ((repl || code) && !values.currentCode && values.replChunks.length === 0)) {
                actions.setReplChunks(repl)
                actions.setCurrentCode(code)
            }
        },
    })),
])
