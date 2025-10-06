import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'

import { tryJsonParse } from 'lib/utils'
import { publicWebhooksHostOrigin } from 'lib/utils/apiHost'

import { HogFunctionConfigurationLogicProps, hogFunctionConfigurationLogic } from '../hogFunctionConfigurationLogic'
import type { hogFunctionSourceWebhookTestLogicType } from './hogFunctionSourceWebhookTestLogicType'

export type HogFunctionSourceWebhookTestForm = {
    method: string
    headers: string
    query: string
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
                method: 'POST',
                headers: `{
  "Content-Type": "application/json"
}`,
                query: '',
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
                const fetchOptions: RequestInit = {
                    method: data.method,
                    headers: tryJsonParse(data.headers),
                    body: data.method == 'GET' ? undefined : data.body,
                    credentials: 'omit',
                }

                const response = await fetch(
                    `${publicWebhooksHostOrigin()}/public/webhooks/${props.id ?? 'unknown'}${data.query ? `?${data.query}` : ''}`,
                    fetchOptions
                )

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

                return `curl -X ${testInvocation.method} ${headers} \\
  -d '${testInvocation.body}' \\
  ${publicWebhooksHostOrigin()}/public/webhooks/${props.id ?? 'unknown'}${testInvocation.query ? `?${testInvocation.query}` : ''}`
            },
        ],
    }),
])
