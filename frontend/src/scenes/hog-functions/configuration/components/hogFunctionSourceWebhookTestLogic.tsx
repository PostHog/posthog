import { actions, connect, kea, key, path, props, reducers } from 'kea'
import { forms } from 'kea-forms'
import { tryJsonParse } from 'lib/utils'

import { HogFunctionTestInvocationResult } from '~/types'

import { hogFunctionConfigurationLogic, HogFunctionConfigurationLogicProps } from '../hogFunctionConfigurationLogic'
import type { hogFunctionSourceWebhookTestLogicType } from './hogFunctionSourceWebhookTestLogicType'

export type HogFunctionSourceWebhookTestInvocationForm = {
    headers: string
    body: string
    mock_request: boolean
}

export const hogFunctionSourceWebhookTestLogic = kea<hogFunctionSourceWebhookTestLogicType>([
    props({} as HogFunctionConfigurationLogicProps),
    key(({ id, templateId }: HogFunctionConfigurationLogicProps) => {
        return id ?? templateId ?? 'new'
    }),

    path((id) => ['scenes', 'pipeline', 'hogfunctions', 'hogFunctionSourceWebhookTestLogic', id]),
    connect((props: HogFunctionConfigurationLogicProps) => ({
        values: [hogFunctionConfigurationLogic(props), ['configuration', 'templateId']],
    })),
    actions({
        setTestResult: (result: HogFunctionTestInvocationResult | null) => ({ result }),
        toggleExpanded: (expanded?: boolean) => ({ expanded }),
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
    }),

    forms(({ props, actions, values }) => ({
        testInvocation: {
            defaults: {
                mock_request: true,
                headers: `{
  "Content-Type": "application/json"
}`,
                body: `{
  "event": "my example event",
  "distinct_id": "webhook-test-123"
}`,
            } as HogFunctionSourceWebhookTestInvocationForm,
            alwaysShowErrors: true,
            errors: ({ headers, body }) => {
                return {
                    headers: !headers ? 'Required' : tryJsonParse(headers) ? undefined : 'Invalid JSON',
                    body: !body ? 'Required' : tryJsonParse(body) ? undefined : 'Invalid JSON',
                }
            },
            submit: async (data) => {
                // Submit the test invocation
                // Set the response somewhere
                // const parsedData = tryJsonParse(data.globals)
                // const configuration = sanitizeConfiguration(values.configuration) as Record<string, any>
                // configuration.template_id = values.templateId
                // // Transformations have a simpler UI just showing the event so we need to map it back to the event
                // const globals =
                //     values.type === 'transformation'
                //         ? {
                //               event: parsedData,
                //           }
                //         : parsedData
                // try {
                //     const res = await api.hogFunctions.createTestInvocation(props.id ?? 'new', {
                //         globals,
                //         mock_async_functions: data.mock_async_functions,
                //         configuration,
                //     })
                //     // Modify the result to match better our globals format
                //     if (values.type === 'transformation' && res.result) {
                //         res.result = convertFromTransformationEvent(res.result)
                //     }
                //     actions.setTestResult(res)
                // } catch (e) {
                //     lemonToast.error(`An unexpected server error occurred while testing the function. ${e}`)
                // }
            },
        },
    })),
])
