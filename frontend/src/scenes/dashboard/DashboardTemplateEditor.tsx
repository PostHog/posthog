import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

export function DashboardTemplateEditor({ inline = false }: { inline?: boolean }): JSX.Element {
    const monaco = useMonaco()

    const { dashboardTemplateJSON, validationError } = useValues(dashboardTemplateEditorLogic)
    const { setDashboardTemplateJSON, updateValidationErrors } = useActions(dashboardTemplateEditorLogic)

    const { closeNewDashboardTemplateModal } = useActions(dashboardTemplateEditorLogic)
    const { isOpenNewDashboardTemplateModal } = useValues(dashboardTemplateEditorLogic)

    const { createDashboardTemplate, updateDashboardTemplate } = useActions(dashboardTemplateEditorLogic)

    const { id } = useValues(dashboardTemplateEditorLogic)

    // const [queryInput, setQueryInput] = useState('hello')

    useEffect(() => {
        if (!monaco) {
            return
        }
        // Would be better if this was dynamic and link to the dashboard template type or the backend
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: [
                {
                    uri: 'http://internal/node-schema.json',
                    fileMatch: ['*'], // associate with our model
                    schema: {
                        type: 'object',
                        required: ['template_name', 'dashboard_description', 'dashboard_filters', 'tiles', 'variables'],
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
                            image_url: {
                                description: 'The image of the dashboard template',
                                type: ['string', 'null'],
                            },
                            dashboard_description: {
                                description: 'The description of the dashboard template',
                                type: 'string',
                            },
                            dashboard_filters: {
                                description: 'The filters of the dashboard template',
                                type: 'object', // TODO: add schema for filters
                            },
                            tiles: {
                                description: 'The tiles of the dashboard template',
                                type: 'array',
                                items: 'object', // TODO: add schema for tiles
                            },
                            variables: {
                                description: 'The variables of the dashboard template',
                                type: 'array',
                                items: {
                                    type: 'object',
                                    required: ['id', 'name', 'type', 'default', 'description', 'required'],
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
                                            type: 'object', // TODO: add schema for default value
                                        },
                                        description: {
                                            description: 'The description of the variable',
                                            type: 'string',
                                        },
                                        required: {
                                            description: 'Whether the variable is required',
                                            type: 'boolean',
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

    return (
        <LemonModal
            title={id ? 'Edit dashboard template' : 'New dashboard template'}
            isOpen={isOpenNewDashboardTemplateModal}
            width={1000}
            onClose={() => {
                closeNewDashboardTemplateModal()
            }}
            inline={inline}
        >
            <MonacoEditor
                theme="vs-light"
                className="border"
                language="json"
                value={dashboardTemplateJSON}
                onChange={(v) => {
                    setDashboardTemplateJSON(v ?? '')
                }}
                onValidate={(markers) => {
                    console.log('on validate', markers)
                    updateValidationErrors(markers)
                }}
                height={600}
            />
            <div className="flex justify-end mt-4">
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
                            closeNewDashboardTemplateModal()
                        }}
                        disabledReason={validationError ? validationError : undefined}
                    >
                        Create new template
                    </LemonButton>
                )}
            </div>
        </LemonModal>
    )
}
