import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'

export function DeleteDashboardModal(): JSX.Element {
    const { hideDeleteDashboardModal } = useActions(deleteDashboardLogic)
    const { isDeleteDashboardSubmitting, deleteDashboardModalVisible } = useValues(deleteDashboardLogic)

    return (
        <LemonModal
            title={'Delete dashboard'}
            onClose={hideDeleteDashboardModal}
            isOpen={deleteDashboardModalVisible}
            footer={
                <>
                    <LemonButton
                        form="delete-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-delete"
                        disabled={isDeleteDashboardSubmitting}
                        onClick={hideDeleteDashboardModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="delete-dashboard-form"
                        htmlType="submit"
                        type="secondary"
                        status={'danger'}
                        data-attr="dashboard-delete-submit"
                        loading={isDeleteDashboardSubmitting}
                        disabled={isDeleteDashboardSubmitting}
                    >
                        Delete dashboard
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={deleteDashboardLogic}
                formKey="deleteDashboard"
                id="delete-dashboard-form"
                enableFormOnSubmit
                className="space-y-2"
            >
                <Field
                    name="deleteInsights"
                    help="This will only delete insights if they're not on any other dashboards."
                >
                    {({ value, onChange }) => (
                        <LemonCheckbox
                            data-attr={'delete-dashboard-insights-checkbox'}
                            checked={value}
                            label="Delete this dashboard's insights"
                            onChange={onChange}
                        />
                    )}
                </Field>
            </Form>
        </LemonModal>
    )
}
