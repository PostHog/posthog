import { useActions, useValues } from 'kea'

import { LemonInput, LemonTable, LemonTableColumns, LemonTabs, LemonTag } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'

import { CodeExampleTab, queryEndpointLogic } from './queryEndpointLogic'

const variablesColumns: LemonTableColumns<Variable> = [
    {
        title: 'Variable Name',
        key: 'code_name',
        dataIndex: 'code_name',
    },
    {
        title: 'Type',
        key: 'type',
        dataIndex: 'type',
    },
    {
        title: 'Default Value',
        key: 'default_value',
        dataIndex: 'default_value',
        render: (_, variable) => variable.default_value || '-',
    },
    {
        title: 'Values',
        key: 'values',
        render: (_, variable) => {
            if (variable.type === 'List' && 'values' in variable && variable.values) {
                return variable.values.join(', ')
            }
            return '-'
        },
    },
]

function generateVariablesJson(variables: Variable[]): string {
    if (variables.length === 0) {
        return '      // No variables defined'
    }

    return variables
        .map((variable, index) => {
            const isLast = index === variables.length - 1
            const comma = isLast ? '' : ','

            let exampleValue = ''
            switch (variable.type) {
                case 'String':
                    exampleValue = `"${variable.default_value || 'example-string'}"`
                    break
                case 'Number':
                    exampleValue = String(variable.default_value || '123')
                    break
                case 'Boolean':
                    exampleValue = String(variable.default_value || 'true')
                    break
                case 'List':
                    exampleValue =
                        variable.type === 'List' && 'values' in variable && variable.values
                            ? JSON.stringify(variable.values)
                            : '["option1", "option2"]'
                    break
                case 'Date':
                    exampleValue = `"${variable.default_value || '2024-01-01'}"`
                    break
                default:
                    exampleValue = '""'
            }

            return `      "${variable.code_name}": ${exampleValue}${comma}`
        })
        .join('\n')
}

function generateTerminalExample(queryEndpointName: string | null, variables: Variable[]): string {
    return `curl -X POST https://us.posthog.com/api/projects/{project_id}/query/${queryEndpointName || 'your-query-name'} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "variables": {
${generateVariablesJson(variables)}
    }
  }'`
}

function generatePythonExample(queryEndpointName: string | null, variables: Variable[]): string {
    return `import requests
import json

url = "https://us.posthog.com/api/projects/{project_id}/query/${queryEndpointName || 'your-query-name'}"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

payload = {
    "variables": {
${generateVariablesJson(variables)}
    }
}

response = requests.post(url, headers=headers, data=json.dumps(payload))
print(response.json())`
}

function generateNodeExample(queryEndpointName: string | null, variables: Variable[]): string {
    return `const fetch = require('node-fetch');

const url = 'https://us.posthog.com/api/projects/{project_id}/query/${queryEndpointName || 'your-query-name'}';

const headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

const payload = {
    "variables": {
${generateVariablesJson(variables)}
    }
};

fetch(url, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(payload)
})
.then(response => response.json())
.then(data => console.log(data))
.catch(error => console.error('Error:', error));`
}

interface CodeExamplesProps {
    queryEndpointName: string | null
    variables: Variable[]
}

function CodeExamples({ queryEndpointName, variables }: CodeExamplesProps): JSX.Element {
    const { setActiveCodeExampleTab } = useActions(queryEndpointLogic)
    const { activeCodeExampleTab } = useValues(queryEndpointLogic)

    const getCodeExample = (tab: CodeExampleTab): string => {
        switch (tab) {
            case 'terminal':
                return generateTerminalExample(queryEndpointName, variables)
            case 'python':
                return generatePythonExample(queryEndpointName, variables)
            case 'nodejs':
                return generateNodeExample(queryEndpointName, variables)
            default:
                return generateTerminalExample(queryEndpointName, variables)
        }
    }

    const getLanguage = (tab: CodeExampleTab): Language => {
        switch (tab) {
            case 'terminal':
                return Language.Bash
            case 'python':
                return Language.Python
            case 'nodejs':
                return Language.JavaScript
            default:
                return Language.Bash
        }
    }

    return (
        <div>
            <h3 className="text-sm font-medium mb-2">Example Usage</h3>
            <LemonTabs
                activeKey={activeCodeExampleTab}
                className="w-2/3"
                size="small"
                onChange={(tab) => setActiveCodeExampleTab(tab as CodeExampleTab)}
                tabs={[
                    {
                        key: 'terminal',
                        label: 'Terminal',
                    },
                    {
                        key: 'python',
                        label: 'Python',
                    },
                    {
                        key: 'nodejs',
                        label: 'Node.js',
                    },
                ]}
            />
            <div className="mt-2 w-2/3">
                <CodeSnippet language={getLanguage(activeCodeExampleTab)} wrap={true}>
                    {getCodeExample(activeCodeExampleTab)}
                </CodeSnippet>
            </div>
        </div>
    )
}

export function QueryEndpoint(): JSX.Element {
    const { setQueryEndpointName } = useActions(queryEndpointLogic)
    const { queryEndpointName } = useValues(queryEndpointLogic)
    const { variablesForInsight } = useValues(variablesLogic)

    return (
        <div className="space-y-4">
            <div className="flex flex-row items-center gap-2">
                <h3 className="mb-0">Query Endpoint</h3>
                <LemonTag type="completion">ALPHA</LemonTag>
            </div>
            <div className="space-y-2">
                <p className="text-xs">
                    Query endpoints are a way of pre-defining queries that you can query via the API, with additional
                    performance improvements and the benefits of monitoring cost and usage.
                    <br />
                    Once created, you will get a URL that you can make an API request to from your own code.
                </p>
                <LemonInput
                    type="text"
                    placeholder="Query name"
                    onChange={setQueryEndpointName}
                    value={queryEndpointName || ''}
                    className="w-1/3"
                />
            </div>

            <div>
                <h3 className="text-sm font-medium mb-2">Variables</h3>
                <LemonTable
                    columns={variablesColumns}
                    dataSource={variablesForInsight}
                    emptyState="No variables defined on the query."
                />
            </div>

            <CodeExamples queryEndpointName={queryEndpointName} variables={variablesForInsight} />
        </div>
    )
}
