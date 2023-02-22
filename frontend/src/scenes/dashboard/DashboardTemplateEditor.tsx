import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardTemplateEditorLogic } from './DashboardTemplateEditorLogic'

export function DashboardTemplateEditor({ inline = false }: { inline?: boolean }): JSX.Element {
    const monaco = useMonaco()

    const { editorValue, validationErrors, templateSchema } = useValues(dashboardTemplateEditorLogic)
    const { setEditorValue, updateValidationErrors } = useActions(dashboardTemplateEditorLogic)

    const { closeDashboardTemplateEditor } = useActions(dashboardTemplateEditorLogic)
    const { isOpenNewDashboardTemplateModal } = useValues(dashboardTemplateEditorLogic)

    const { createDashboardTemplate, updateDashboardTemplate } = useActions(dashboardTemplateEditorLogic)

    const { id } = useValues(dashboardTemplateEditorLogic)

    useEffect(() => {
        if (!monaco) {
            return
        }

        console.log('templateSchema', templateSchema)

        const schemas = []
        if (templateSchema) {
            schemas.push({
                uri: 'http://internal/node-schema.json',
                fileMatch: ['*'],
                schema: templateSchema,
            })
        } // TODO: better error handling if it can't load the template schema

        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: schemas,
        })
    }, [monaco, templateSchema])

    return (
        <LemonModal
            title={id ? 'Edit dashboard template' : 'New dashboard template'}
            isOpen={isOpenNewDashboardTemplateModal}
            width={1000}
            onClose={() => {
                closeDashboardTemplateEditor()
            }}
            inline={inline}
        >
            <MonacoEditor
                theme="vs-light"
                className="border"
                language="json"
                value={editorValue}
                onChange={(v) => {
                    setEditorValue(v ?? '')
                }}
                onValidate={(markers) => {
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
                        disabledReason={
                            validationErrors.length
                                ? `There are ${validationErrors.length} errors to resolve: ${validationErrors.map(
                                      (e) => ' ' + e
                                  )}`
                                : undefined
                        }
                    >
                        Update template
                    </LemonButton>
                ) : (
                    <LemonButton
                        onClick={() => {
                            createDashboardTemplate()
                            closeDashboardTemplateEditor()
                        }}
                        disabledReason={
                            validationErrors.length
                                ? `There are ${validationErrors.length} errors to resolve:${validationErrors.map(
                                      (e) => ' ' + e
                                  )}`
                                : undefined
                        }
                    >
                        Create new template
                    </LemonButton>
                )}
            </div>
        </LemonModal>
    )
}
