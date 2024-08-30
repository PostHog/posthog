import { VMState } from '@posthog/hogvm'
import { printHogValue } from '@posthog/hogvm/src/stl/print'
import { LemonButton, LemonDivider, lemonToast } from '@posthog/lemon-ui'
import equal from 'fast-deep-equal'
import { actions, kea, listeners, path, reducers, selectors, useActions, useValues } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { execHog } from 'lib/hog'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { SceneExport } from 'scenes/sceneTypes'

import type { notebookTestLogicType } from './NotebookTestType'

export interface ExecResult {
    // code?: string
    // bytecode?: any[]
    stdout: string
    state: VMState
}

/*
This is a notebook with bytecodes. Input: list of strings, codes, output

 */

export const notebookTestLogic = kea<notebookTestLogicType>([
    path(['scenes', 'debug', 'NotebookTest']),
    actions({
        updateCode: (index: number, code: string) => ({ index, code }),
        updateCodes: (codes: string[]) => ({ codes }),
        compileBytecode: true,
        updateBytecode: (bytecode: any[], fetchedUntil: number) => ({ bytecode, fetchedUntil }),
        runFrom: (index: number) => ({ index }),
        setExecResult: (index: number, execResult: ExecResult) => ({ index, execResult }),
    }),
    reducers({
        codes: [
            [] as string[],
            {
                updateCode: (state, { index, code }) => {
                    const newState = [...state]
                    newState[index] = code
                    return newState
                },
                updateCodes: (_, { codes }) => codes,
            },
        ],
        bytecodeUntil: [
            0,
            {
                updateCode: (state, { index }) => Math.min(state, index - 1),
                updateBytecode: (_, { fetchedUntil }) => fetchedUntil,
            },
        ],
        runUntil: [
            0,
            {
                updateCode: (state, { index }) => Math.min(state, index - 1),
                setExecResult: (state, { index }) => Math.max(state, index),
            },
        ],
        bytecode: [
            [] as any[],
            {
                updateBytecode: (_, { bytecode }) => bytecode,
            },
        ],
        execResults: [
            [] as ExecResult[],
            {
                // updateBytecode: (_, { bytecode }) => bytecode,
                setExecResult: (state, { index, execResult }) => {
                    const newState = [...state]
                    newState[index] = execResult
                    return newState
                },
                updateCode: (state, { index }) => state.slice(0, index),
            },
        ],
    }),
    selectors({
        combinedCode: [
            (s) => [s.codes],
            (codes) =>
                Object.values(codes)
                    .map((code, index) => [code, `;__nbbb__(${index});`].join('\n'))
                    .join('\n'),
        ],
        outputs: [(s) => [s.execResults], (execResults): string[] => execResults.map(({ stdout }) => stdout ?? '')],
    }),
    listeners(({ actions, values }) => ({
        updateCode: () => actions.compileBytecode(),
        updateCodes: () => actions.compileBytecode(),
        compileBytecode: async (_, breakpoint) => {
            await breakpoint(300)
            // recompile all the code
            const fetchedUntil = values.codes.length
            let response
            try {
                response = await api.hog.create(values.combinedCode)
            } catch (e) {
                lemonToast.error(`Unable to compile bytecode: ${e}`)
                console.error(e)
                return
            }
            breakpoint()
            // update the bytecode
            if (response && 'bytecode' in response && Array.isArray(response.bytecode)) {
                actions.updateBytecode(response.bytecode, fetchedUntil)
            }
            // set as
        },
        runFrom: async ({ index }) => {
            if (index > values.bytecodeUntil) {
                return
            }
            const bytecode = values.bytecode
            let stdout: string[] = []

            let nextState: any[] | VMState = bytecode

            if (index > 0 && values.execResults[index - 1]) {
                // add the new bytecode even if the rest of the state is old, the compiled section should not have changed
                nextState = { ...values.execResults[index - 1].state, bytecode: bytecode }
            }

            while (true) {
                const response = execHog(nextState, {
                    functions: {
                        print: (...args) => {
                            stdout.push(args.map((a) => printHogValue(a)).join(' '))
                        },
                    },
                    asyncFunctions: {
                        __nbbb__: async () => true, // not actually a function
                    },
                })
                if (response.finished) {
                    break
                }
                if (
                    response.asyncFunctionName === '__nbbb__' &&
                    Array.isArray(response.asyncFunctionArgs) &&
                    response.state
                ) {
                    const index = response.asyncFunctionArgs[0]
                    nextState = { ...response.state, stack: [...(response.state.stack || []), null] }
                    actions.setExecResult(index, {
                        stdout: stdout.join('\n'),
                        state: nextState,
                    })
                    stdout = []
                } else {
                    lemonToast.error(`Unknown async function: ${response.asyncFunctionName}`)
                    break
                }
            }
        },
    })),
    actionToUrl(({ values }) => ({
        updateCode: () => ['/hogbooks', {}, { codes: values.codes }],
    })),
    urlToAction(({ actions, values }) => ({
        '/hogbooks': (_, __, { codes }) => {
            if (codes && !equal(codes, values.codes)) {
                actions.updateCodes(codes)
            }
        },
    })),
])

export function NotebookTest(): JSX.Element {
    const { codes, outputs, bytecodeUntil, runUntil } = useValues(notebookTestLogic)
    const { runFrom, updateCode } = useActions(notebookTestLogic)
    const blocks = 3
    return (
        <div className="NotebookTest space-y-2">
            <div>Bytecode until: {bytecodeUntil}</div>
            <div>Run until: {runUntil}</div>
            {Array.from({ length: blocks }).map((_, i) => (
                <div key={i} className="space-y-2">
                    <p>Code {i + 1}</p>
                    <div>
                        <CodeEditorResizeable
                            language="hog"
                            value={codes[i] ?? ''}
                            onChange={(v) => updateCode(i, v ?? '')}
                        />
                    </div>
                    <LemonButton
                        size="xsmall"
                        disabledReason={bytecodeUntil < i ? 'Could not compile until here' : null}
                        type="primary"
                        onClick={() => runFrom(i)}
                    >
                        Run from here
                    </LemonButton>
                    <p>Output {i + 1}</p>
                    <div className="font-mono whitespace-pre">{runUntil >= i ? outputs[i] : '...'}</div>
                    <LemonDivider />
                </div>
            ))}
        </div>
    )
}

export const scene: SceneExport = {
    component: NotebookTest,
    logic: notebookTestLogic,
}
