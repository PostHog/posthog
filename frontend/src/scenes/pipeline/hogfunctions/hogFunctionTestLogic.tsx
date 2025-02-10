import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { tryJsonParse } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { editor } from 'monaco-editor'

import { groupsModel } from '~/models/groupsModel'
import { HogFunctionInvocationGlobals, HogFunctionTestInvocationResult } from '~/types'

import {
    hogFunctionConfigurationLogic,
    HogFunctionConfigurationLogicProps,
    sanitizeConfiguration,
} from './hogFunctionConfigurationLogic'
import type { hogFunctionTestLogicType } from './hogFunctionTestLogicType'

export type HogFunctionTestInvocationForm = {
    globals: string // HogFunctionInvocationGlobals
    mock_async_functions: boolean
}

export type HogTransformationEvent = {
    event: any
    uuid: string
    distinct_id: string
    timestamp: string
    properties: any
}

const convertToTransformationEvent = (result: any): HogTransformationEvent => {
    const properties = result.properties ?? {}
    properties.$ip = properties.$ip ?? '89.160.20.129'
    return {
        event: result.event,
        uuid: result.uuid,
        distinct_id: result.distinct_id,
        timestamp: result.timestamp,
        properties,
    }
}

const convertFromTransformationEvent = (result: HogTransformationEvent): Record<string, any> => {
    return {
        event: result.event,
        uuid: result.uuid,
        distinct_id: result.distinct_id,
        timestamp: result.timestamp,
        properties: result.properties,
    }
}

export interface CodeEditorValidation {
    value: string
    editor: editor.IStandaloneCodeEditor
    decorations: string[]
}

export const hogFunctionTestLogic = kea<hogFunctionTestLogicType>([
    props({} as HogFunctionConfigurationLogicProps),
    key(({ id, templateId }: HogFunctionConfigurationLogicProps) => {
        return id ?? templateId ?? 'new'
    }),

    path((id) => ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionTestLogic', id]),
    connect((props: HogFunctionConfigurationLogicProps) => ({
        values: [
            hogFunctionConfigurationLogic(props),
            [
                'configuration',
                'templateId',
                'configurationHasErrors',
                'sampleGlobals',
                'sampleGlobalsLoading',
                'exampleInvocationGlobals',
                'sampleGlobalsError',
                'type',
            ],
            groupsModel,
            ['groupTypes'],
        ],
        actions: [
            hogFunctionConfigurationLogic(props),
            ['touchConfigurationField', 'loadSampleGlobalsSuccess', 'loadSampleGlobals', 'setSampleGlobals'],
        ],
    })),
    actions({
        setTestResult: (result: HogFunctionTestInvocationResult | null) => ({ result }),
        toggleExpanded: (expanded?: boolean) => ({ expanded }),
        saveGlobals: (name: string, globals: HogFunctionInvocationGlobals) => ({ name, globals }),
        deleteSavedGlobals: (index: number) => ({ index }),
        setTestResultMode: (mode: 'raw' | 'diff') => ({ mode }),
        receiveExampleGlobals: (globals: HogFunctionInvocationGlobals | null) => ({ globals }),
        setJsonError: (error: string | null) => ({ error }),
        validateJson: (value: string, editor: editor.IStandaloneCodeEditor, decorations: string[]) =>
            ({ value, editor, decorations } as CodeEditorValidation),
        setDecorationIds: (decorationIds: string[]) => ({ decorationIds }),
    }),
    reducers({
        expanded: [
            false as boolean,
            {
                toggleExpanded: (state, { expanded }) => (expanded === undefined ? !state : expanded),
            },
        ],

        testResult: [
            null as HogFunctionTestInvocationResult | null,
            {
                setTestResult: (_, { result }) => result,
            },
        ],

        testResultMode: [
            'diff' as 'raw' | 'diff',
            {
                setTestResultMode: (_, { mode }) => mode,
            },
        ],

        savedGlobals: [
            [] as { name: string; globals: HogFunctionInvocationGlobals }[],
            { persist: true, prefix: `${getCurrentTeamId()}__` },
            {
                saveGlobals: (state, { name, globals }) => [...state, { name, globals }],
                deleteSavedGlobals: (state, { index }) => state.filter((_, i) => i !== index),
            },
        ],

        jsonError: [
            null as string | null,
            {
                setJsonError: (_, { error }) => error,
            },
        ],

        currentDecorationIds: [
            [] as string[],
            {
                setDecorationIds: (_, { decorationIds }) => decorationIds,
                setJsonError: () => [], // Clear decorations when error state changes
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        loadSampleGlobalsSuccess: () => {
            actions.receiveExampleGlobals(values.sampleGlobals)
        },
        setSampleGlobals: ({ sampleGlobals }) => {
            actions.receiveExampleGlobals(sampleGlobals)
        },

        receiveExampleGlobals: ({ globals }) => {
            if (!globals) {
                return
            }

            if (values.type === 'transformation') {
                const event = convertToTransformationEvent(globals.event)
                // Strip down to just the real values
                actions.setTestInvocationValue('globals', JSON.stringify(event, null, 2))
            } else {
                actions.setTestInvocationValue('globals', JSON.stringify(globals, null, 2))
            }
        },

        validateJson: ({ value, editor, decorations }: CodeEditorValidation) => {
            if (!editor?.getModel()) {
                return
            }

            const model = editor.getModel()!

            try {
                // Try parsing the JSON
                JSON.parse(value)
                // If valid, ensure everything is cleared
                actions.setJsonError(null)
                editor.removeDecorations(decorations)
            } catch (err: any) {
                actions.setJsonError(err.message)

                const match = err.message.match(/position (\d+)/)
                if (!match) {
                    return
                }

                const position = parseInt(match[1], 10)
                const pos = model.getPositionAt(position)

                // Set single error marker
                editor.createDecorationsCollection([
                    {
                        range: {
                            startLineNumber: pos.lineNumber,
                            startColumn: pos.column,
                            endLineNumber: pos.lineNumber,
                            endColumn: pos.column + 1,
                        },
                        options: {
                            isWholeLine: true,
                            className: 'bg-danger-highlight',
                            glyphMarginClassName: 'text-danger flex items-center justify-center',
                            glyphMarginHoverMessage: { value: err.message },
                        },
                    },
                ])
                // Scroll to error
                editor.revealLineInCenter(pos.lineNumber)
            }
        },
    })),

    forms(({ props, actions, values }) => ({
        testInvocation: {
            defaults: {
                mock_async_functions: false,
            } as HogFunctionTestInvocationForm,
            alwaysShowErrors: true,
            errors: ({ globals }) => {
                return {
                    globals: !globals ? 'Required' : tryJsonParse(globals) ? undefined : 'Invalid JSON',
                }
            },
            submit: async (data) => {
                // Submit the test invocation
                // Set the response somewhere

                if (values.configurationHasErrors) {
                    lemonToast.error('Please fix the configuration errors before testing.')
                    // TODO: How to get the form to show errors without submitting?
                    return
                }

                const parsedData = tryJsonParse(data.globals)
                const configuration = sanitizeConfiguration(values.configuration) as Record<string, any>
                configuration.template_id = values.templateId

                // Transformations have a simpler UI just showing the event so we need to map it back to the event
                const globals =
                    values.type === 'transformation'
                        ? {
                              event: parsedData,
                          }
                        : parsedData

                try {
                    const res = await api.hogFunctions.createTestInvocation(props.id ?? 'new', {
                        globals,
                        mock_async_functions: data.mock_async_functions,
                        configuration,
                    })

                    // Modify the result to match better our globals format
                    if (values.type === 'transformation' && res.result) {
                        res.result = convertFromTransformationEvent(res.result)
                    }

                    actions.setTestResult(res)
                } catch (e) {
                    lemonToast.error(`An unexpected server error occurred while testing the function. ${e}`)
                }
            },
        },
    })),

    selectors(() => ({
        sortedTestsResult: [
            (s) => [s.configuration, s.testResult, s.testInvocation],
            (
                configuration,
                testResult,
                testInvocation
            ): {
                input: string
                output: string
                hasDiff: boolean
            } | null => {
                if (!testResult || configuration.type !== 'transformation') {
                    return null
                }

                const input = JSON.stringify(JSON.parse(testInvocation.globals), null, 2)
                const output = JSON.stringify(testResult.result, null, 2)

                return {
                    input,
                    output,
                    hasDiff: input !== output,
                }
            },
        ],
    })),

    afterMount(({ actions, values }) => {
        if (values.type === 'transformation') {
            actions.receiveExampleGlobals(values.exampleInvocationGlobals)
        }
    }),
])
