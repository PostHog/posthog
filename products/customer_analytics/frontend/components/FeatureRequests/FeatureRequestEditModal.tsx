import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { FeatureRequestStatusEnumApi, FeatureRequestPriorityEnumApi } from '../../generated/api.schemas'
import { FEATURE_REQUEST_PRIORITY_OPTIONS, FEATURE_REQUEST_STATUS_OPTIONS } from './featureRequestOptions'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestEditModal(): JSX.Element {
    const {
        editRequestOpen,
        activeRequest,
        accountOptions,
        editProductAreaOptions,
        accountsLoading,
        productAreasLoading,
        editError,
        editIsStale,
        isFeatureRequestEditFormSubmitting,
    } = useValues(featureRequestsLogic)
    const { closeEditRequest, setAccountSearch, submitFeatureRequestEditForm, reloadLatestForEdit } =
        useActions(featureRequestsLogic)

    return (
        <LemonModal
            isOpen={editRequestOpen}
            onClose={closeEditRequest}
            title="Edit feature request"
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeEditRequest}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitFeatureRequestEditForm}
                        loading={isFeatureRequestEditFormSubmitting}
                        data-attr="save-feature-request-changes"
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <Form logic={featureRequestsLogic} formKey="featureRequestEditForm" className="flex flex-col gap-4">
                {editError && (
                    <LemonBanner
                        type="error"
                        action={
                            editIsStale ? { children: 'Load latest version', onClick: reloadLatestForEdit } : undefined
                        }
                    >
                        {editError}
                    </LemonBanner>
                )}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <LemonField
                        name="requestStatus"
                        label="Status"
                        help={activeRequest?.github_link ? 'Changing the status pauses GitHub sync.' : undefined}
                    >
                        <LemonSelect<FeatureRequestStatusEnumApi> options={FEATURE_REQUEST_STATUS_OPTIONS} fullWidth />
                    </LemonField>
                    <LemonField name="requestPriority" label="Priority">
                        {({ value, onChange }) => (
                            <LemonSelect<FeatureRequestPriorityEnumApi | 'none'>
                                value={value ?? 'none'}
                                onChange={(priority) => onChange(priority === 'none' ? null : priority)}
                                options={[{ value: 'none', label: 'No priority' }, ...FEATURE_REQUEST_PRIORITY_OPTIONS]}
                                fullWidth
                            />
                        )}
                    </LemonField>
                </div>
                <LemonField name="title" label="Title">
                    <LemonInput maxLength={400} fullWidth />
                </LemonField>
                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea minRows={5} />
                </LemonField>
                <LemonField name="accountIds" label="Accounts">
                    <LemonInputSelect
                        mode="multiple"
                        onInputChange={setAccountSearch}
                        options={accountOptions}
                        placeholder="Search for accounts"
                        loading={accountsLoading}
                        fullWidth
                    />
                </LemonField>
                <LemonField name="productAreaIds" label="Product areas">
                    <LemonInputSelect
                        mode="multiple"
                        options={editProductAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </LemonField>
            </Form>
        </LemonModal>
    )
}
