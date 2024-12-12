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

export type TreeFileNode = { replChunks: ReplChunk[]; currentCode: string }
export type TreeNode = { [key: string]: TreeNode | TreeFileNode }
export type FileArrayNode = { path: string } & TreeFileNode

function buildFileTree(files: FileArrayNode[]): TreeNode {
    const tree: TreeNode = {}

    files.forEach(({ path, ...fileNode }) => {
        const parts = []
        for (const part of path.split('/')) {
            if (part === '' && parts.length > 0) {
                // if a part is '', add '/' to the previous element in the array
                parts[parts.length - 1] += '/'
            } else {
                parts.push(part)
            }
        }

        let currentLevel = tree

        parts.forEach((part, index) => {
            if (index === parts.length - 1) {
                currentLevel[part] = fileNode
            } else {
                if (!currentLevel[part]) {
                    currentLevel[part] = {}
                }
                currentLevel = currentLevel[part] as TreeNode
            }
        })
    })

    return tree
}

const replaceLast = (arr: any[], newElement: any): any[] => ((arr[arr.length - 1] = newElement), arr)

export const isTreeFileNode = (node: TreeNode | TreeFileNode): node is TreeFileNode => {
    return typeof node === 'object' && node !== null && 'replChunks' in node && 'currentCode' in node
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

        setCurrentFile: (path: string) => ({ path }),
        deleteFile: (path: string) => ({ path }),
        renameFile: (path: string, name: string) => ({ path, name }),
        newFile: (path: string) => ({ path }),
        addNewFile: (path: string) => ({ path }),
        updateFile: (path: string, changes: Partial<TreeFileNode>) => ({ path, changes }),
        setFiles: (files: FileArrayNode[]) => ({ files }),
    }),
    reducers({
        currentFile: [
            'posthog://blank.hog',
            {
                setCurrentFile: (_, { path }) => path,
                addNewFile: (_, { path }) => path,
            },
        ],
        files: [
            [] as FileArrayNode[],
            {
                setFiles: (_, { files }) => files,
                setCurrentFile: (state, { path }) =>
                    state.find((file) => file.path === path)
                        ? state
                        : [...state, { path, replChunks: [], currentCode: '' }],
                deleteFile: (state, { path }) => state.filter((file) => file.path !== path),
                renameFile: (state, { path, name }) =>
                    state.map((file) =>
                        file.path === path ? { ...file, path: replaceLast(file.path.split('/'), name).join('/') } : file
                    ),
                addNewFile: (state, { path }) => [...state, { path, replChunks: [], currentCode: '' }],
                updateFile: (state, { path, changes }) =>
                    state.find((file) => file.path === path)
                        ? state.map((s) => (s.path === path ? { ...s, ...changes } : s))
                        : [...state, { path, replChunks: [], currentCode: '', ...changes }],
            },
        ],
    }),
    selectors({
        currentCode: [
            (s) => [s.files, s.currentFile],
            (files, currentFile): string => files.find((f) => f.path === currentFile)?.currentCode ?? '',
        ],
        replChunks: [
            (s) => [s.files, s.currentFile],
            (files, currentFile): ReplChunk[] => files.find((f) => f.path === currentFile)?.replChunks ?? [],
        ],
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
        fileTree: [
            (s) => [s.files],
            (files) => {
                const tree = buildFileTree(files)
                if (Object.keys(tree).length === 0) {
                    return { 'posthog:/': {} }
                }
                return tree
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        newFile: ({ path }) => {
            const filename = window.prompt('Enter the name of the new file', 'newFile.hog')
            actions.addNewFile([path || 'posthog:/', filename ?? 'newFile.hog'].join('/'))
        },
        editFromHere: ({ index }) => {
            const code = [...values.replChunks.slice(index).map((chunk) => chunk.code), values.currentCode].join('\n')
            actions.setCurrentCode(code.replace(/\n+$/, ''))
            actions.setReplChunks(values.replChunks.slice(0, index))
        },
        runCode: async ({ code }) => {
            actions.updateFile(values.currentFile, {
                replChunks: [...values.replChunks, { code, status: 'pending' } as ReplChunk],
            })

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
        setCurrentCode: ({ code }) => {
            actions.updateFile(values.currentFile, { currentCode: code })
        },
        setReplChunks: ({ replChunks }) => {
            actions.updateFile(values.currentFile, { replChunks })
        },
        setResult: ({ index, result, error }) =>
            actions.updateFile(values.currentFile, {
                replChunks: values.replChunks.map((chunk, i) =>
                    i === index ? { ...chunk, result, error, status: error ? 'error' : 'success' } : chunk
                ),
            }),
        setBytecode: ({ index, bytecode, locals }) =>
            actions.updateFile(values.currentFile, {
                replChunks: values.replChunks.map((chunk, i) => (i === index ? { ...chunk, bytecode, locals } : chunk)),
            }),
        print: ({ index, line }) =>
            actions.updateFile(values.currentFile, {
                replChunks: values.replChunks.map((chunk, i) =>
                    i === index ? { ...chunk, print: [...(chunk.print ?? []), line] } : chunk
                ),
            }),
        setVMState: ({ index, state: vmState }) =>
            actions.updateFile(values.currentFile, {
                replChunks: values.replChunks.map((chunk, i) => (i === index ? { ...chunk, state: vmState } : chunk)),
            }),
    })),
    actionToUrl(({ values }) => {
        const fn = (): [string, undefined, Record<string, any> | undefined, { replace: true }] | undefined => {
            // Chrome has a 2MB limit for the HASH params, set ours at 1MB
            const filesLength = JSON.stringify(values.files).length
            if (filesLength > 1024 * 1024) {
                // Can't store this much in the url
                return [urls.debugHog(), undefined, undefined, { replace: true }]
            }

            return [
                urls.debugHog(),
                undefined,
                { files: values.files, currentFile: values.currentFile },
                { replace: true },
            ]
        }

        return {
            setReplChunks: fn,
            runCode: fn,
            setResult: fn,
            setBytecode: fn,
            print: fn,
            setVMState: fn,
            setCurrentCode: fn,
            setCurrentFile: fn,
            deleteFile: fn,
            renameFile: fn,
            addNewFile: fn,
            updateFile: fn,
        }
    }),
    urlToAction(({ actions, values }) => ({
        [urls.debugHog()]: (_, __, { repl, code, files, currentFile }) => {
            if (files) {
                actions.setFiles(files)
                if (currentFile && currentFile !== values.currentFile) {
                    actions.setCurrentFile(currentFile)
                }
            } else if ((repl || code) && !values.currentCode && values.replChunks.length === 0) {
                actions.setReplChunks(repl)
                actions.setCurrentCode(code)
            } else {
                actions.setFiles([{ path: 'posthog://blank.hog', replChunks: [], currentCode: '' }])
            }
        },
    })),
])
