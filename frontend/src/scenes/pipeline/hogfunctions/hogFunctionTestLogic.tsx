import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { tryJsonParse } from 'lib/utils'

import { DataTableNode, NodeKind } from '~/queries/schema'
import {
    HogFunctionConfigurationType,
    HogFunctionInvocationGlobals,
    LogEntry,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { hogFunctionTestLogicType } from './hogFunctionTestLogicType'
import { createExampleGlobals } from './utils/event-conversion'

export interface HogFunctionTestLogicProps {
    id: string
    configuration: HogFunctionConfigurationType
}

export type HogFunctionTestInvocationForm = {
    globals: string // HogFunctionInvocationGlobals
    mock_async_functions: boolean
}

export type HogFunctionTestInvocationResult = {
    status: 'success' | 'error'
    logs: LogEntry[]
}

// Should likely be somewhat similar to pipelineBatchExportConfigurationLogic
export const hogFunctionTestLogic = kea<hogFunctionTestLogicType>([
    props({} as HogFunctionTestLogicProps),
    key((props) => props.id),
    path((id) => ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionTestLogic', id]),
    actions({
        setTestEvent: (event: string | null) => ({ event }),
        setTestResult: (result: HogFunctionTestInvocationResult | null) => ({ result }),
    }),
    reducers({
        testEvent: [
            JSON.stringify(createExampleGlobals()) as string | null,
            {
                setTestEvent: (_, { event }) => event,
            },
        ],

        testResult: [
            null as HogFunctionTestInvocationResult | null,
            {
                setTestResult: (_, { result }) => result,
            },
        ],
    }),
    forms(({ props, actions }) => ({
        testInvocation: {
            defaults: {
                mock_async_functions: true,
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

                const globals: HogFunctionInvocationGlobals = tryJsonParse(data.globals)

                try {
                    const res = await api.hogFunctions.createTestInvocation(props.id, {
                        globals,
                        mock_async_functions: data.mock_async_functions,
                        configuration: props.configuration,
                    })

                    actions.setTestResult(res)
                } catch (e) {
                    console.error(e)
                }
            },
        },
    })),
    selectors(() => ({
        matchingEventsQuery: [
            (_, p) => [p.configuration],
            ({ filters }): DataTableNode | null => {
                if (!filters) {
                    return null
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: ['event'],
                        properties: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$browser',
                                operator: PropertyOperator.Exact,
                                value: 'Chrome',
                            },
                        ],
                    },
                    full: false,
                    showEventFilter: false,
                    showPropertyFilter: false,
                    showTimings: false,
                    showOpenEditorButton: false,
                    expandable: true,
                    showColumnConfigurator: false,
                    embedded: true,
                }
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.setTestInvocationValue('globals', JSON.stringify(createExampleGlobals(), null, 2))
    }),
])
