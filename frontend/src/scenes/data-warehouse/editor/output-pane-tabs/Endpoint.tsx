import { useActions, useValues } from 'kea'

import { IconCode2 } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
    lemonToast,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { NodeKind } from '~/queries/schema/schema-general'

import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'
import { endpointsLogic } from 'products/endpoints/frontend/endpointsLogic'

import { multitabEditorLogic } from '../multitabEditorLogic'

interface EndpointProps {
    tabId: string
}

export function Endpoint({ tabId }: EndpointProps): JSX.Element {
    const {
        setEndpointName,
        setEndpointDescription,
        setIsUpdateMode,
        setSelectedEndpointName,
        createEndpoint,
        updateEndpoint,
    } = useActions(endpointLogic({ tabId }))
    const { endpointName, endpointDescription, isUpdateMode, selectedEndpointName } = useValues(
        endpointLogic({ tabId })
    )
    const { endpoints } = useValues(endpointsLogic({ tabId }))

    const { variablesForInsight } = useValues(variablesLogic)
    const { queryInput } = useValues(multitabEditorLogic)

    const handleSubmit = (): void => {
        const sqlQuery = queryInput || ''
        if (!sqlQuery.trim()) {
            lemonToast.error('You are missing a HogQL query.')
            return
        }

        if (isUpdateMode && !selectedEndpointName) {
            lemonToast.error('You need to select an endpoint to update.')
            return
        }

        if (!isUpdateMode && !endpointName) {
            lemonToast.error('You need to name your endpoint.')
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
                      {} as Record<string, { variableId: string; code_name: string; value?: any }>
                  )
                : {}

        const queryPayload = {
            kind: NodeKind.HogQLQuery as const,
            query: sqlQuery,
            variables: transformedVariables,
        }

        if (isUpdateMode && selectedEndpointName) {
            updateEndpoint(selectedEndpointName, {
                description: endpointDescription || undefined,
                query: queryPayload,
            })
        } else {
            createEndpoint({
                name: endpointName || undefined,
                description: endpointDescription || undefined,
                query: queryPayload,
            })
        }
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-row items-center gap-2">
                <h3 className="mb-0">Endpoint</h3>
                <LemonTag type="completion">ALPHA</LemonTag>
            </div>
            <div className="space-y-2">
                <p className="text-xs">
                    Endpoints are a way of pre-defining queries that you can query via the API, with additional
                    performance improvements and the benefits of monitoring cost and usage.
                    <br />
                    Once created, you will get a URL that you can make an API request to from your own code.
                </p>

                <div className="flex items-center gap-2">
                    <LemonSwitch
                        checked={isUpdateMode}
                        onChange={(checked) => {
                            setIsUpdateMode(checked)
                            if (checked) {
                                setEndpointName('')
                            } else {
                                setSelectedEndpointName(null)
                            }
                        }}
                        label="Update existing endpoint"
                    />
                </div>

                {isUpdateMode ? (
                    <LemonField.Pure label="Select endpoint">
                        <LemonSelect
                            value={selectedEndpointName}
                            onChange={(value) => setSelectedEndpointName(value)}
                            options={endpoints.map((endpoint) => ({
                                value: endpoint.name,
                                label: endpoint.name,
                            }))}
                            placeholder="Select an endpoint to update"
                            className="w-1/3"
                        />
                    </LemonField.Pure>
                ) : (
                    <LemonField.Pure label="Endpoint name">
                        <LemonInput
                            id={`endpoint-name-${tabId}`}
                            type="text"
                            onChange={setEndpointName}
                            value={endpointName || ''}
                            className="w-1/3"
                        />
                    </LemonField.Pure>
                )}

                <LemonField.Pure label="Endpoint description">
                    <LemonTextArea
                        minRows={1}
                        maxRows={3}
                        onChange={setEndpointDescription}
                        value={endpointDescription || ''}
                        className="w-1/3"
                    />
                </LemonField.Pure>

                <LemonButton type="primary" onClick={handleSubmit} icon={<IconCode2 />} size="medium">
                    {isUpdateMode ? 'Update endpoint' : 'Create endpoint'}
                </LemonButton>
            </div>
        </div>
    )
}
