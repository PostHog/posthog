import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { editor } from 'monaco-editor'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { tryJsonParse } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { groupsModel } from '~/models/groupsModel'
import { CyclotronJobInvocationGlobals, CyclotronJobTestInvocationResult } from '~/types'

import {
    HogFunctionConfigurationLogicProps,
    hogFunctionConfigurationLogic,
    sanitizeConfiguration,
} from './hogFunctionConfigurationLogic'
import type { hogFunctionTestLogicType } from './hogFunctionTestLogicType'

export type HogFunctionTestInvocationForm = {
    globals: string // CyclotronJobInvocationGlobals
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
    // We don't want to use these values given they will change in the test invocation
    delete properties.$transformations_failed
    delete properties.$transformations_succeeded
    delete properties.$transformations_skipped
    return {
        event: result.event,
        uuid: result.uuid,
        distinct_id: result.distinct_id,
        timestamp: result.timestamp,
        properties,
    }
}

const convertFromTransformationEvent = (result: HogTransformationEvent): Record<string, any> => {
    delete result.properties.$transformations_failed
    delete result.properties.$transformations_succeeded
    delete result.properties.$transformations_skipped
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
                'currentHogCode',
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
        setTestResult: (result: CyclotronJobTestInvocationResult | null) => ({ result }),
        toggleExpanded: (expanded?: boolean) => ({ expanded }),
        saveGlobals: (name: string, globals: CyclotronJobInvocationGlobals) => ({ name, globals }),
        deleteSavedGlobals: (index: number) => ({ index }),
        setTestResultMode: (mode: 'raw' | 'diff') => ({ mode }),
        receiveExampleGlobals: (globals: CyclotronJobInvocationGlobals | null) => ({ globals }),
        setJsonError: (error: string | null) => ({ error }),
        validateJson: (value: string, editor: editor.IStandaloneCodeEditor, decorations: string[]) =>
            ({
                value,
                editor,
                decorations,
            }) as CodeEditorValidation,
        setDecorationIds: (decorationIds: string[]) => ({ decorationIds }),
        cancelSampleGlobalsLoading: true,
    }),
    reducers({
        expanded: [
            false as boolean,
            {
                toggleExpanded: (state, { expanded }) => (expanded === undefined ? !state : expanded),
            },
        ],

        testResult: [
            null as CyclotronJobTestInvocationResult | null,
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
            [] as { name: string; globals: CyclotronJobInvocationGlobals }[],
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

        fetchCancelled: [
            false as boolean,
            {
                loadSampleGlobals: () => false,
                cancelSampleGlobalsLoading: () => true,
                toggleExpanded: () => false,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        loadSampleGlobalsSuccess: () => {
            if (values.expanded && !values.fetchCancelled && values.sampleGlobals) {
                actions.receiveExampleGlobals(values.sampleGlobals)
            }
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

        setTestResult: ({ result }) => {
            if (result) {
                setTimeout(() => {
                    // First try to scroll the test results container into view
                    const testResults = document.querySelector('[data-attr="test-results"]')
                    if (testResults) {
                        testResults.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    }

                    // Find the Monaco editor and scroll to the first difference
                    const editors = document.querySelectorAll('[data-attr="test-results"] .monaco-editor')
                    if (editors.length > 0 && values.sortedTestsResult?.hasDiff) {
                        const lastEditor = editors[editors.length - 1]
                        const monacoEditor = lastEditor.querySelector('.monaco-scrollable-element')
                        if (monacoEditor) {
                            const inputLines = values.sortedTestsResult.input.split('\n')
                            const outputLines = values.sortedTestsResult.output.split('\n')

                            // Find the first line that differs
                            let diffLineIndex = 0
                            for (let i = 0; i < Math.max(inputLines.length, outputLines.length); i++) {
                                if (inputLines[i] !== outputLines[i]) {
                                    diffLineIndex = i
                                    break
                                }
                            }

                            // Calculate approximate scroll position for the diff, showing 2 lines of context above
                            const lineHeight = 19 // Default Monaco line height
                            monacoEditor.scrollTop = Math.max(0, (diffLineIndex - 2) * lineHeight)
                        }
                    }
                }, 100)
            }
        },

        cancelSampleGlobalsLoading: () => {
            // Just mark as cancelled - we'll ignore any results that come back
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
                    // Get the configuration logic instance
                    const configLogic = hogFunctionConfigurationLogic(props)
                    const inputErrors = configLogic.values.inputFormErrors || {}

                    // Create a simple list of errors
                    const errorMessages = Object.entries(inputErrors).map(([key, error]) => {
                        const errorText = typeof error === 'string' ? error : 'Invalid format'
                        return `${key}: ${errorText}`
                    })

                    // Show the error message
                    const message =
                        errorMessages.length > 0
                            ? `Please fix the following errors:\n${errorMessages.join('\n')}`
                            : 'Please fix the configuration errors before testing.'

                    lemonToast.error(message, {
                        toastId: 'hogfunction-validation-error',
                    })

                    // Show the errors in the UI
                    configLogic.actions.touchConfigurationField && configLogic.actions.touchConfigurationField('inputs')
                    return
                }

                const parsedData = tryJsonParse(data.globals)
                const configuration = sanitizeConfiguration(values.configuration) as Record<string, any>
                configuration.template_id = values.templateId
                configuration.hog = values.currentHogCode

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
                } catch (e: any) {
                    if (e?.data?.configuration?.filters?.non_field_errors) {
                        lemonToast.error(`Testing failed: ${e.data.configuration.filters.non_field_errors}`)
                        return
                    }
                    lemonToast.error(`An unexpected server error occurred while testing the function: ${e}`)
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

                const rawInput = convertFromTransformationEvent(
                    convertToTransformationEvent(JSON.parse(testInvocation.globals))
                )

                const input = JSON.stringify(rawInput, null, 2)
                const output = JSON.stringify(testResult.result, null, 2)

                return {
                    input,
                    output,
                    hasDiff: input !== output,
                }
            },
        ],

        sampleGlobalsLoadingAndNotCancelled: [
            (s) => [s.sampleGlobalsLoading, s.fetchCancelled],
            (sampleGlobalsLoading, fetchCancelled) => sampleGlobalsLoading && !fetchCancelled,
        ],
    })),

    afterMount(({ actions, values }) => {
        actions.receiveExampleGlobals(values.exampleInvocationGlobals)
    }),
])
