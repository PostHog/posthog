import { useActions, useValues } from 'kea'

import { LemonButton } from 'lib/components/LemonButton'

import { LemonModal } from 'lib/components/LemonModal'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { saveDashboardTemplateLogic } from 'scenes/dashboard/dashboardTemplates/saveDashboardTemplateLogic'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'

export function SaveDashboardTemplateModal(): JSX.Element {
    const { hideSaveDashboardTemplateModal } = useActions(saveDashboardTemplateLogic)
    const { saveDashboardTemplateModalVisible, isSaveDashboardTemplateSubmitting } =
        useValues(saveDashboardTemplateLogic)

    return (
        <LemonModal
            title={'Saved as dashboard template'}
            onClose={hideSaveDashboardTemplateModal}
            isOpen={saveDashboardTemplateModalVisible}
            footer={
                <>
                    <LemonButton
                        form="save-dashboard-template-form"
                        type="secondary"
                        data-attr="save-dashboard-template-cancel"
                        disabled={isSaveDashboardTemplateSubmitting}
                        onClick={hideSaveDashboardTemplateModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="save-dashboard-template-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="save-dashboard-template-submit"
                        loading={isSaveDashboardTemplateSubmitting}
                        disabled={isSaveDashboardTemplateSubmitting}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={saveDashboardTemplateLogic}
                formKey="saveDashboardTemplate"
                id="save-dashboard-template-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <Field name="templateName" label={'Template name'}>
                    <LemonInput autoFocus={true} data-attr={'save-dashboard-template-name'} />
                </Field>
            </Form>
        </LemonModal>
    )
}
