import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/components/LemonButton'

import { LemonModal } from 'lib/components/LemonModal'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { importDashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/importDashboardTemplateLogic'
import { LemonFileInput } from 'lib/components/LemonFileInput/LemonFileInput'
import { createRef } from 'react'

export function ImportDashboardTemplateModal(): JSX.Element {
    const { hideImportDashboardTemplateModal, refreshGlobalDashboardTemplate } =
        useActions(importDashboardTemplateLogic)
    const {
        importDashboardTemplateModalVisible,
        isImportDashboardTemplateSubmitting,
        dashboardTemplateRefreshLoading,
    } = useValues(importDashboardTemplateLogic)
    const dropRef = createRef<HTMLDivElement>()

    return (
        <LemonModal
            title={'Import a dashboard template'}
            onClose={hideImportDashboardTemplateModal}
            isOpen={importDashboardTemplateModalVisible}
            footer={
                <>
                    <div className={'flex-1'}>
                        <LemonButton
                            type="secondary"
                            data-attr={'refresh-global-dashboard-templates'}
                            disabled={isImportDashboardTemplateSubmitting || dashboardTemplateRefreshLoading}
                            loading={dashboardTemplateRefreshLoading}
                            onClick={refreshGlobalDashboardTemplate}
                        >
                            Refresh global templates
                        </LemonButton>
                    </div>
                    <LemonButton
                        form="import-dashboard-template-form"
                        type="secondary"
                        data-attr="import-dashboard-template-cancel"
                        disabled={isImportDashboardTemplateSubmitting || dashboardTemplateRefreshLoading}
                        onClick={hideImportDashboardTemplateModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="import-dashboard-template-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="import-dashboard-template-submit"
                        loading={isImportDashboardTemplateSubmitting}
                        disabled={isImportDashboardTemplateSubmitting || dashboardTemplateRefreshLoading}
                    >
                        Upload
                    </LemonButton>
                </>
            }
        >
            <div ref={dropRef} className={'p-2'}>
                <Form
                    logic={importDashboardTemplateLogic}
                    formKey="importDashboardTemplate"
                    id="import-dashboard-template-form"
                    enableFormOnSubmit
                    className="space-y-2"
                >
                    <Field name="templateJson" label={'Template file'}>
                        <LemonFileInput
                            alternativeDropTargetRef={dropRef}
                            accept={'.json'}
                            multiple={false}
                            data-attr={'save-dashboard-template-name'}
                        />
                    </Field>
                </Form>
            </div>
        </LemonModal>
    )
}
