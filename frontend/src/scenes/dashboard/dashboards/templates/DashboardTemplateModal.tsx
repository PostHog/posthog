import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonInputSelect, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { dashboardTemplateEditorLogic } from 'scenes/dashboard/dashboardTemplateEditorLogic'
import { userLogic } from 'scenes/userLogic'

import type { DashboardTemplateEditorType } from '~/types'

import { dashboardTemplateModalLogic } from './dashboardTemplateModalLogic'

export function DashboardTemplateModal(): JSX.Element | null {
    const {
        isOpen,
        mode,
        templateName,
        dashboardDescription,
        templateTags,
        projectTemplateSaveLoading,
        createPayload,
        editingTemplate,
    } = useValues(dashboardTemplateModalLogic)
    const { closeModal, setTemplateName, setDashboardDescription, setTemplateTags, saveProjectTemplate } =
        useActions(dashboardTemplateModalLogic)
    const { user } = useValues(userLogic)
    const { setDashboardTemplate, setDashboardTemplateId, openDashboardTemplateEditor } =
        useActions(dashboardTemplateEditorLogic)

    if (!isOpen) {
        return null
    }

    const saving = !!projectTemplateSaveLoading
    const handleClose = (): void => {
        if (saving) {
            return
        }
        closeModal()
    }

    const openFullJsonEditor = (): void => {
        if (saving) {
            return
        }
        const tags = templateTags.map((t) => t.trim()).filter(Boolean)
        if (mode === 'create') {
            if (!createPayload) {
                return
            }
            const payload: DashboardTemplateEditorType = {
                ...createPayload,
                template_name: templateName.trim() || createPayload.template_name,
                dashboard_description: dashboardDescription,
                tags,
            }
            setDashboardTemplate(payload)
            setDashboardTemplateId(null)
        } else {
            if (!editingTemplate) {
                return
            }
            const payload: DashboardTemplateEditorType = {
                ...editingTemplate,
                template_name: templateName.trim() || editingTemplate.template_name,
                dashboard_description: dashboardDescription,
                tags,
            }
            setDashboardTemplate(payload)
            setDashboardTemplateId(editingTemplate.id, { hydrateEditorFromApi: false })
        }
        openDashboardTemplateEditor()
        closeModal()
    }

    const showStaffJsonTools = Boolean(user?.is_staff && (mode === 'create' || mode === 'edit'))
    const jsonEditorDisabled = saving || (mode === 'create' ? !createPayload : !editingTemplate)

    return (
        <LemonModal
            title={mode === 'create' ? 'Save as dashboard template' : 'Edit dashboard template'}
            onClose={handleClose}
            maxWidth="32rem"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal} disabled={saving}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => saveProjectTemplate()}
                        loading={saving}
                        disabled={
                            (mode === 'create' && !createPayload) || (mode === 'edit' && !editingTemplate) || saving
                        }
                    >
                        {mode === 'create' ? 'Save template' : 'Save changes'}
                    </LemonButton>
                </>
            }
        >
            <div className={showStaffJsonTools ? 'space-y-4' : 'space-y-3'}>
                {showStaffJsonTools && (
                    <div
                        className="flex flex-col gap-4 rounded-md border border-border bg-fill-secondary px-4 py-4"
                        data-attr="dashboard-template-staff-tools"
                    >
                        <div className="flex flex-col gap-1.5">
                            <p className="m-0 text-sm font-semibold leading-snug">Staff tools</p>
                            <p className="text-secondary text-xs m-0 leading-relaxed max-w-prose">
                                Full JSON editor for official templates and fields not available in this form.
                            </p>
                        </div>
                        <LemonButton
                            type="secondary"
                            size="small"
                            disabled={jsonEditorDisabled}
                            onClick={openFullJsonEditor}
                            data-attr="dashboard-template-open-full-json-editor"
                            className="self-start"
                        >
                            Open full JSON editor
                        </LemonButton>
                    </div>
                )}
                <div className={showStaffJsonTools ? 'space-y-3 border-t border-border pt-4' : 'space-y-3'}>
                    <div>
                        <label className="font-semibold text-sm">Name</label>
                        <LemonInput
                            value={templateName}
                            onChange={setTemplateName}
                            placeholder="e.g. Weekly KPIs"
                            fullWidth
                            disabled={saving}
                            data-attr="dashboard-template-name"
                        />
                    </div>
                    <div>
                        <label className="font-semibold text-sm">Description</label>
                        <LemonTextArea
                            value={dashboardDescription}
                            onChange={setDashboardDescription}
                            placeholder="What this template is for"
                            minRows={3}
                            maxRows={8}
                            maxLength={400}
                            disabled={saving}
                            data-attr="dashboard-template-description"
                        />
                    </div>
                    <div>
                        <label className="font-semibold text-sm">Tags</label>
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            value={templateTags}
                            onChange={setTemplateTags}
                            placeholder='Add tags like "kpi" or "growth"'
                            fullWidth
                            disabled={saving}
                            data-attr="dashboard-template-tags"
                        />
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
