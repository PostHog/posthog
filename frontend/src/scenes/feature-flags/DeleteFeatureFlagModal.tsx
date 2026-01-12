import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { deleteFeatureFlagLogic } from './deleteFeatureFlagLogic'

export function DeleteFeatureFlagModal(): JSX.Element {
    const { hideDeleteFeatureFlagModal } = useActions(deleteFeatureFlagLogic)
    const { isDeleteFeatureFlagSubmitting, deleteFeatureFlagModalVisible, deleteFeatureFlag } =
        useValues(deleteFeatureFlagLogic)

    return (
        <LemonModal
            title="Delete feature flag"
            onClose={hideDeleteFeatureFlagModal}
            isOpen={deleteFeatureFlagModalVisible}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        disabled={isDeleteFeatureFlagSubmitting}
                        onClick={hideDeleteFeatureFlagModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="delete-feature-flag-form"
                        htmlType="submit"
                        type="secondary"
                        status="danger"
                        data-attr="feature-flag-delete-submit"
                        loading={isDeleteFeatureFlagSubmitting}
                        disabled={isDeleteFeatureFlagSubmitting}
                    >
                        Delete feature flag
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={deleteFeatureFlagLogic}
                formKey="deleteFeatureFlag"
                id="delete-feature-flag-form"
                enableFormOnSubmit
            >
                <p>
                    Are you sure you want to delete "<strong>{deleteFeatureFlag.featureFlagKey}</strong>"?
                </p>

                {deleteFeatureFlag.hasUsageDashboard && (
                    <LemonField name="deleteUsageDashboard" className="mt-4">
                        {({ value, onChange }) => (
                            <LemonCheckbox
                                data-attr="delete-feature-flag-dashboard-checkbox"
                                checked={value}
                                label="Also delete the usage dashboard and insights"
                                onChange={onChange}
                            />
                        )}
                    </LemonField>
                )}
            </Form>
        </LemonModal>
    )
}
