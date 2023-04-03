import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'

export function DashboardTemplateEditor({ inline = false }: { inline?: boolean }): JSX.Element {
    const monaco = useMonaco()

    const {
        closeDashboardTemplateEditor,
        createDashboardTemplate,
        updateDashboardTemplate,
        setEditorValue,
        updateValidationErrors,
    } = useActions(dashboardTemplateEditorLogic)

    const { isOpenNewDashboardTemplateModal, editorValue, validationErrors, templateSchema, id } =
        useValues(dashboardTemplateEditorLogic)

    useEffect(() => {
        if (!monaco) {
            return
        }

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
            footer={
                id ? (
                    <LemonButton
                        type={'primary'}
                        data-attr="update-dashboard-template-button"
                        onClick={() => {
                            updateDashboardTemplate({ id })
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
                        type={'primary'}
                        data-attr="create-dashboard-template-button"
                        onClick={() => {
                            createDashboardTemplate()
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
                )
            }
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
                loading={<Spinner />}
            />
        </LemonModal>
    )
}
