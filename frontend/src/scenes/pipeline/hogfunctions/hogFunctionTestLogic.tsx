import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { tryJsonParse } from 'lib/utils'

import { groupsModel } from '~/models/groupsModel'
import { LogEntry } from '~/types'

import { hogFunctionConfigurationLogic, sanitizeConfiguration } from './hogFunctionConfigurationLogic'
import type { hogFunctionTestLogicType } from './hogFunctionTestLogicType'

export interface HogFunctionTestLogicProps {
    id: string
}

export type HogFunctionTestInvocationForm = {
    globals: string // HogFunctionInvocationGlobals
    mock_async_functions: boolean
}

export type HogFunctionTestInvocationResult = {
    status: 'success' | 'error'
    logs: LogEntry[]
}

export const hogFunctionTestLogic = kea<hogFunctionTestLogicType>([
    props({} as HogFunctionTestLogicProps),
    key((props) => props.id),
    path((id) => ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionTestLogic', id]),
    connect((props: HogFunctionTestLogicProps) => ({
        values: [
            hogFunctionConfigurationLogic({ id: props.id }),
            ['configuration', 'configurationHasErrors', 'sampleGlobals'],
            groupsModel,
            ['groupTypes'],
        ],
        actions: [
            hogFunctionConfigurationLogic({ id: props.id }),
            ['touchConfigurationField', 'loadSampleGlobalsSuccess'],
        ],
    })),
    actions({
        setTestResult: (result: HogFunctionTestInvocationResult | null) => ({ result }),
        toggleExpanded: (expanded?: boolean) => ({ expanded }),
    }),
    reducers({
        expanded: [
            false as boolean,
            {
                toggleExpanded: (_, { expanded }) => (expanded === undefined ? !_ : expanded),
            },
        ],

        testResult: [
            null as HogFunctionTestInvocationResult | null,
            {
                setTestResult: (_, { result }) => result,
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        loadSampleGlobalsSuccess: () => {
            actions.setTestInvocationValue('globals', JSON.stringify(values.sampleGlobals, null, 2))
        },
    })),
    forms(({ props, actions, values }) => ({
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

                if (values.configurationHasErrors) {
                    lemonToast.error('Please fix the configuration errors before testing.')
                    // TODO: How to get the form to show errors without submitting?
                    return
                }

                const globals = tryJsonParse(data.globals)
                const configuration = sanitizeConfiguration(values.configuration)

                try {
                    const res = await api.hogFunctions.createTestInvocation(props.id, {
                        globals,
                        mock_async_functions: data.mock_async_functions,
                        configuration,
                    })

                    actions.setTestResult(res)
                } catch (e) {
                    lemonToast.error(`An unexpected serror occurred while trying to testing the function. ${e}`)
                }
            },
        },
    })),

    afterMount(({ actions }) => {
        actions.setTestInvocationValue('globals', '{/* Please wait, fetching a real event. */}')
    }),
])
