import { useActions, useValues } from 'kea'

import { IconCode2 } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonTable,
    LemonTableColumns,
    LemonTabs,
    LemonTag,
    LemonTextArea,
    lemonToast,
} from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { projectLogic } from 'scenes/projectLogic'

import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'
import { NodeKind } from '~/queries/schema/schema-general'

import { multitabEditorLogic } from '../multitabEditorLogic'
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

function getNamedQueryEndpointUrl(projectId: number | undefined, queryEndpointName: string | null): string {
    return `${window.location.origin}/${projectId}/named_query/d/${queryEndpointName || 'your-query-name'}`
}

function generateTerminalExample(
    queryEndpointName: string | null,
    variables: Variable[],
    projectId: number | undefined
): string {
    return `curl -X POST ${getNamedQueryEndpointUrl(projectId, queryEndpointName)} \\
  -H "Authorization: Bearer $POSTHOG_PERSONAL_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "variables_values": {
${generateVariablesJson(variables)}
    }
  }'`
}

function generatePythonExample(
    queryEndpointName: string | null,
    variables: Variable[],
    projectId: number | undefined
): string {
    return `import requests
import json

url = "${getNamedQueryEndpointUrl(projectId, queryEndpointName)}"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
}

payload = {
    "variables_values": {
${generateVariablesJson(variables)}
    }
}

response = requests.post(url, headers=headers, data=json.dumps(payload))
print(response.json())`
}

function generateNodeExample(
    queryEndpointName: string | null,
    variables: Variable[],
    projectId: number | undefined
): string {
    return `const fetch = require('node-fetch');

const url = '${getNamedQueryEndpointUrl(projectId, queryEndpointName)}';

const headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer {POSTHOG_PERSONAL_API_KEY}'
};

const payload = {
    "variables_values": {
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
    projectId: number | undefined
    tabId: string
}

interface QueryEndpointProps {
    tabId: string
}

function CodeExamples({ queryEndpointName, variables, projectId, tabId }: CodeExamplesProps): JSX.Element {
    const { setActiveCodeExampleTab } = useActions(queryEndpointLogic({ tabId }))
    const { activeCodeExampleTab } = useValues(queryEndpointLogic({ tabId }))

    const getCodeExample = (tab: CodeExampleTab): string => {
        switch (tab) {
            case 'terminal':
                return generateTerminalExample(queryEndpointName, variables, projectId)
            case 'python':
                return generatePythonExample(queryEndpointName, variables, projectId)
            case 'nodejs':
                return generateNodeExample(queryEndpointName, variables, projectId)
            default:
                return generateTerminalExample(queryEndpointName, variables, projectId)
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

export function QueryEndpoint({ tabId }: QueryEndpointProps): JSX.Element {
    const { setQueryEndpointName, setQueryEndpointDescription, createQueryEndpoint } = useActions(
        queryEndpointLogic({ tabId })
    )
    const { queryEndpointName, queryEndpointDescription } = useValues(queryEndpointLogic({ tabId }))

    const { currentProject } = useValues(projectLogic)
    const { variablesForInsight } = useValues(variablesLogic)
    const { queryInput } = useValues(multitabEditorLogic)

    const handleCreateQueryEndpoint = (): void => {
        const sqlQuery = queryInput || ''
        if (!sqlQuery.trim()) {
            lemonToast.error('You are missing a HogQL query.')
            return
        }

        if (!queryEndpointName?.trim()) {
            lemonToast.error('You need to name your query endpoint.')
            return
        }

        const transformedVariables =
            variablesForInsight.length > 0
                ? variablesForInsight.reduce(
                      (acc, variable, index) => {
                          acc[`var_${index}`] = {
                              variableId: variable.id,
                              code_name: variable.code_name,
                              value: variable.value || variable.default_value,
                          }
                          return acc
                      },
                      {} as Record<string, { variableId: string; code_name: string; value: any }>
                  )
                : {}

        createQueryEndpoint({
            name: queryEndpointName,
            description: queryEndpointDescription || '',
            query: {
                kind: NodeKind.HogQLQuery,
                query: sqlQuery,
                variables: transformedVariables,
            },
        })
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-row items-center gap-2">
                <h3 className="mb-0">Query endpoint</h3>
                <LemonTag type="completion">ALPHA</LemonTag>
            </div>
            <div className="space-y-2">
                <p className="text-xs">
                    Query endpoints are a way of pre-defining queries that you can query via the API, with additional
                    performance improvements and the benefits of monitoring cost and usage.
                    <br />
                    Once created, you will get a URL that you can make an API request to from your own code.
                </p>
                <LemonField.Pure label="Query name">
                    <LemonInput
                        id={`query-endpoint-name-${tabId}`}
                        type="text"
                        onChange={setQueryEndpointName}
                        value={queryEndpointName || ''}
                        className="w-1/3"
                    />
                </LemonField.Pure>

                <LemonField.Pure label="Query description">
                    <LemonTextArea
                        minRows={1}
                        maxRows={3}
                        onChange={setQueryEndpointDescription}
                        value={queryEndpointDescription || ''}
                        className="w-1/3"
                    />
                </LemonField.Pure>

                <LemonButton type="primary" onClick={handleCreateQueryEndpoint} icon={<IconCode2 />} size="medium">
                    Create query endpoint
                </LemonButton>
            </div>

            <div>
                <h3 className="text-sm font-medium mb-2">Variables</h3>
                <LemonTable
                    columns={variablesColumns}
                    dataSource={variablesForInsight}
                    emptyState="No variables used in the query."
                />
            </div>

            <CodeExamples
                queryEndpointName={queryEndpointName}
                variables={variablesForInsight}
                projectId={currentProject?.id}
                tabId={tabId}
            />
        </div>
    )
}
