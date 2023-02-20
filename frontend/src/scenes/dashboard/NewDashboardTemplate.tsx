import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { newDashboardTemplateLogic } from './NewDashboardTemplateLogic'

export function NewDashboardTemplate({ inline = false }: { inline: boolean }): JSX.Element {
    const monaco = useMonaco()

    const { dashboardTemplateJSON, validationError } = useValues(newDashboardTemplateLogic)
    const { setDashboardTemplateJSON, updateValidationErrors } = useActions(newDashboardTemplateLogic)

    const { setOpenNewDashboardTemplateModal } = useActions(newDashboardTemplateLogic)
    const { isOpenNewDashboardTemplateModal } = useValues(newDashboardTemplateLogic)

    const { createDashboardTemplate, updateDashboardTemplate } = useActions(newDashboardTemplateLogic)

    const { id } = useValues(newDashboardTemplateLogic)

    // const [queryInput, setQueryInput] = useState('hello')

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: [
                {
                    uri: 'http://internal/node-schema.json',
                    fileMatch: ['*'], // associate with our model
                    schema: {
                        type: 'object',
                        required: ['template_name', 'dashboard_description', 'dashboard_filters', 'tiles', 'variables'],
                        additionalProperties: false,
                        properties: {
                            id: {
                                description: 'The id of the dashboard template',
                                type: 'string',
                            },
                            template_name: {
                                description: 'The name of the dashboard template',
                                type: 'string',
                            },
                            team_id: {
                                description: 'The team this dashboard template belongs to',
                                type: 'number',
                            },
                            created_at: {
                                description: 'When the dashboard template was created',
                                type: 'string',
                            },
                            dashboard_description: {
                                description: 'The description of the dashboard template',
                                type: 'string',
                            },
                            dashboard_filters: {
                                description: 'The filters of the dashboard template',
                                type: 'object',
                            },
                            tiles: {
                                description: 'The tiles of the dashboard template',
                                type: 'array',
                                items: 'object',
                            },
                            variables: {
                                description: 'The variables of the dashboard template',
                                type: 'array',
                                items: {
                                    type: 'object',
                                    required: ['id', 'name', 'type', 'default', 'description'],
                                    properties: {
                                        id: {
                                            description: 'The id of the variable',
                                            type: 'string',
                                        },
                                        name: {
                                            description: 'The name of the variable',
                                            type: 'string',
                                        },
                                        type: {
                                            description: 'The type of the variable',
                                            enum: ['event'],
                                        },
                                        default: {
                                            description: 'The default value of the variable',
                                            type: 'object',
                                        },
                                        description: {
                                            description: 'The description of the variable',
                                            type: 'string',
                                        },
                                    },
                                },
                            },
                            tags: {
                                description: 'The tags of the dashboard template',
                                type: 'array',
                                items: {
                                    type: 'string',
                                },
                            },
                        },
                    },
                },
            ],
        })
    }, [monaco])

    // disable the new dashboard template button if there's a monaco validation error

    return (
        <LemonModal
            title="New Dashboard Template"
            isOpen={isOpenNewDashboardTemplateModal}
            width={800}
            onClose={() => {
                setOpenNewDashboardTemplateModal(false)
            }}
            inline={inline}
        >
            <div>
                {id ? (
                    <LemonButton
                        onClick={() => {
                            updateDashboardTemplate(id)
                        }}
                        disabledReason={validationError ? validationError : undefined}
                    >
                        Update template
                    </LemonButton>
                ) : (
                    <LemonButton
                        onClick={() => {
                            createDashboardTemplate(dashboardTemplateJSON)
                            setOpenNewDashboardTemplateModal(false)
                        }}
                        disabledReason={validationError ? validationError : undefined}
                    >
                        Create new template
                    </LemonButton>
                )}
            </div>
            <MonacoEditor
                theme="vs-light"
                className="border"
                language="json"
                value={dashboardTemplateJSON}
                onChange={(v) => {
                    setDashboardTemplateJSON(v ?? '')
                }}
                height={500}
                onValidate={(markers) => {
                    console.log('on validate', markers)
                    updateValidationErrors(markers)
                }}
            />
        </LemonModal>
    )
}
