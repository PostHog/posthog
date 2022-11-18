import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/components/LemonButton'

import { LemonModal } from 'lib/components/LemonModal'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { importDashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/importDashboardTemplateLogic'
import { LemonFileInput } from 'lib/components/LemonFileInput/LemonFileInput'

export function ImportDashboardTemplateModal(): JSX.Element {
    const { hideImportDashboardTemplateModal } = useActions(importDashboardTemplateLogic)
    const { importDashboardTemplateModalVisible, isImportDashboardTemplateSubmitting } =
        useValues(importDashboardTemplateLogic)

    return (
        <LemonModal
            title={'Import a dashboard template'}
            onClose={hideImportDashboardTemplateModal}
            isOpen={importDashboardTemplateModalVisible}
            footer={
                <>
                    <LemonButton
                        form="import-dashboard-template-form"
                        type="secondary"
                        data-attr="import-dashboard-template-cancel"
                        disabled={isImportDashboardTemplateSubmitting}
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
                        disabled={isImportDashboardTemplateSubmitting}
                    >
                        Upload
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={importDashboardTemplateLogic}
                formKey="importDashboardTemplate"
                id="import-dashboard-template-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <Field name="templateJson" label={'Template file'}>
                    <LemonFileInput accept={'*.json'} multiple={false} data-attr={'save-dashboard-template-name'} />
                </Field>
            </Form>
        </LemonModal>
    )
}
