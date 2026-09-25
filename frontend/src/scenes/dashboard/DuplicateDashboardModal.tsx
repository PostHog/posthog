import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'

export function DuplicateDashboardModal(): JSX.Element {
    const { hideDuplicateDashboardModal } = useActions(duplicateDashboardLogic)
    const { isDuplicateDashboardSubmitting, duplicateDashboardModalVisible, duplicateRequestId } =
        useValues(duplicateDashboardLogic)

    return (
        <LemonModal
            title="Duplicate dashboard"
            onClose={duplicateRequestId === null ? hideDuplicateDashboardModal : undefined}
            isOpen={duplicateDashboardModalVisible}
            footer={
                <>
                    <LemonButton
                        form="new-dashboard-form"
                        type="secondary"
                        data-attr="dashboard-cancel"
                        disabled={isDuplicateDashboardSubmitting || duplicateRequestId !== null}
                        onClick={hideDuplicateDashboardModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="duplicate-dashboard-form"
                        htmlType="submit"
                        type="primary"
                        data-attr="duplicate-dashboard-submit"
                        loading={isDuplicateDashboardSubmitting || duplicateRequestId !== null}
                        disabled={isDuplicateDashboardSubmitting || duplicateRequestId !== null}
                    >
                        Duplicate
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={duplicateDashboardLogic}
                formKey="duplicateDashboard"
                id="duplicate-dashboard-form"
                enableFormOnSubmit
                className="deprecated-space-y-2"
            >
                <LemonField
                    name="duplicateTiles"
                    help="Choose whether to duplicate this dashboard's insights and text or attach them to the new dashboard."
                >
                    {({ value, onChange }) => (
                        <LemonCheckbox checked={value} label="Duplicate this dashboard's tiles" onChange={onChange} />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
