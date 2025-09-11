import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

export function DashboardTemplateEditor({ inline = false }: { inline?: boolean }): JSX.Element {
    const {
        closeDashboardTemplateEditor,
        createDashboardTemplate,
        updateDashboardTemplate,
        setEditorValue,
        updateValidationErrors,
    } = useActions(dashboardTemplateEditorLogic)

    const { isOpenNewDashboardTemplateModal, editorValue, validationErrors, templateSchema, id } =
        useValues(dashboardTemplateEditorLogic)

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
                        type="primary"
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
                        type="primary"
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
            <CodeEditor
                className="border"
                language="json"
                value={editorValue}
                onChange={(v) => {
                    setEditorValue(v ?? '')
                }}
                onValidate={(markers) => {
                    updateValidationErrors(markers)
                }}
                path={id ? `dashboard-templates/${id}.json` : 'dashboard-templates/new.json'}
                schema={templateSchema}
                height={600}
            />
        </LemonModal>
    )
}
