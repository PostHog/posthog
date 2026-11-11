import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeEditor } from 'lib/monaco/CodeEditor'

import type { MonacoMarker } from '~/types'

import { dashboardTemplateEditorLogic } from './dashboardTemplateEditorLogic'

export interface DashboardTemplateEditorProps {
    inline?: boolean
}

export function DashboardTemplateEditor({ inline = false }: DashboardTemplateEditorProps): JSX.Element {
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
                onChange={(v: string | undefined) => setEditorValue(v ?? '')}
                onValidate={(markers: MonacoMarker[] | undefined) => updateValidationErrors(markers)}
                path={id ? `dashboard-templates/${id}.json` : 'dashboard-templates/new.json'}
                schema={templateSchema}
                height={600}
            />
        </LemonModal>
    )
}
