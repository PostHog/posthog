import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { tryJsonParse } from 'lib/utils'

import { hogFunctionConfigurationLogic, HogFunctionConfigurationLogicProps } from '../hogFunctionConfigurationLogic'
import type { hogFunctionSourceWebhookTestLogicType } from './hogFunctionSourceWebhookTestLogicType'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'

export type HogFunctionSourceWebhookTestForm = {
    headers: string
    body: string
    mock_request: boolean
}

export type HogFunctionSourceWebhookTestResult = {
    status: number
    body: string
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
        setTestResult: (result: HogFunctionSourceWebhookTestResult | null) => ({ result }),
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
            null as HogFunctionSourceWebhookTestResult | null,
            {
                setTestResult: (_, { result }) => result,
            },
        ],
    }),

    forms(({ props, actions }) => ({
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
            } as HogFunctionSourceWebhookTestForm,
            alwaysShowErrors: true,
            errors: ({ headers, body }) => {
                return {
                    headers: !headers ? 'Required' : tryJsonParse(headers) ? undefined : 'Invalid JSON',
                    body: !body ? 'Required' : tryJsonParse(body) ? undefined : 'Invalid JSON',
                }
            },
            submit: async (data) => {
                actions.setTestResult(null)

                const response = await fetch(`${apiHostOrigin()}/public/webhooks/${props.id ?? 'unknown'}`, {
                    method: 'POST',
                    headers: tryJsonParse(data.headers),
                    body: data.body,
                })

                actions.setTestResult({
                    status: response.status,
                    body: await response.text(),
                })
            },
        },
    })),

    selectors({
        exampleCurlRequest: [
            (s) => [s.testInvocation, (_, props) => props],
            (testInvocation, props) => {
                const headersJson = tryJsonParse(testInvocation.headers)
                const headers = headersJson
                    ? Object.entries(headersJson)
                          .map(([key, value]) => `-H "${key}: ${value}"`)
                          .join(' ')
                    : ''

                return `curl -X POST ${headers} \\
  -d '${testInvocation.body}' \\
  ${publicWebhooksHostOrigin()}/public/webhooks/${props.id ?? 'unknown'}`
            },
        ],
    }),
])
