import { useActions, useValues } from 'kea'

import { IconCode2 } from '@posthog/icons'
import { LemonButton, LemonInput, LemonTag, LemonTextArea, Link, lemonToast } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { variablesLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variablesLogic'
import { NodeKind } from '~/queries/schema/schema-general'

import { endpointLogic } from 'products/endpoints/frontend/endpointLogic'

import { sqlEditorLogic } from '../sqlEditorLogic'

interface EndpointProps {
    tabId: string
}

export function Endpoint({ tabId }: EndpointProps): JSX.Element {
    const { setEndpointName, setEndpointDescription, createEndpoint, updateEndpoint } = useActions(
        endpointLogic({ tabId })
    )
    const { endpointName, endpointDescription } = useValues(endpointLogic({ tabId }))

    const { variablesForInsight } = useValues(variablesLogic)
    const { queryInput, editingEndpoint } = useValues(sqlEditorLogic)

    const handleSubmit = (): void => {
        const sqlQuery = queryInput || ''
        if (!sqlQuery.trim()) {
            lemonToast.error('You are missing a HogQL query.')
            return
        }

        if (!editingEndpoint && !endpointName) {
            lemonToast.error('You need to name your endpoint.')
            return
        }

        const transformedVariables = Object.fromEntries(
            variablesForInsight.map((variable) => [
                variable.id,
                {
                    variableId: variable.id,
                    code_name: variable.code_name,
                    value: variable.value || variable.default_value,
                    isNull: variable.isNull || false,
                },
            ])
        )

        const queryPayload = {
            kind: NodeKind.HogQLQuery as const,
            query: sqlQuery,
            variables: transformedVariables,
        }

        if (editingEndpoint) {
            updateEndpoint(
                editingEndpoint.name,
                {
                    description: endpointDescription || undefined,
                    query: queryPayload,
                },
                { showViewButton: true }
            )
        } else {
            createEndpoint({
                name: endpointName || undefined,
                description: endpointDescription || undefined,
                query: queryPayload,
            })
        }
    }

    return (
        <div className="overflow-auto" data-attr="sql-editor-endpoint-pane">
            <div className="flex flex-row items-center gap-2">
                <h3 className="mb-0">Endpoint</h3>
                <LemonTag type="warning">BETA</LemonTag>
            </div>
            <div className="space-y-2">
                <p className="text-xs">
                    Endpoints allows you to pre-define a query that you'd like to expose as an API endpoint to use in
                    your customer-facing dashboard, on your landing page or in your internal tool.
                    <br />
                    <Link data-attr="endpoints-help" to="https://posthog.com/docs/endpoints" target="_blank">
                        Learn more about endpoints.
                    </Link>
                </p>

                <LemonField.Pure label="Endpoint name">
                    {editingEndpoint ? (
                        <LemonInput
                            id={`endpoint-name-${tabId}`}
                            type="text"
                            value={editingEndpoint.name}
                            disabledReason="Editing existing endpoint."
                            className="max-w-prose"
                        />
                    ) : (
                        <LemonInput
                            id={`endpoint-name-${tabId}`}
                            type="text"
                            onChange={setEndpointName}
                            value={endpointName || ''}
                            className="max-w-prose"
                        />
                    )}
                </LemonField.Pure>

                <LemonField.Pure label="Endpoint description">
                    <LemonTextArea
                        minRows={1}
                        maxRows={3}
                        onChange={setEndpointDescription}
                        value={endpointDescription || ''}
                        className="max-w-prose"
                    />
                </LemonField.Pure>

                <LemonButton type="primary" onClick={handleSubmit} icon={<IconCode2 />} size="medium">
                    {editingEndpoint ? 'Update endpoint' : 'Create endpoint'}
                </LemonButton>
            </div>
        </div>
    )
}
