import { useActions, useValues } from 'kea'

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
        editTitle,
        editDescription,
        editAccountIds,
        editProductAreaIds,
        editStatus,
        editPriority,
        accountOptions,
        editProductAreaOptions,
        accountsLoading,
        productAreasLoading,
        editError,
        editIsStale,
        savingRequestChanges,
        editDisabledReason,
        editFormErrors,
        showEditFormErrors,
    } = useValues(featureRequestsLogic)
    const {
        closeEditRequest,
        setEditTitle,
        setEditDescription,
        setEditAccountIds,
        setAccountSearch,
        setEditProductAreaIds,
        setEditStatus,
        setEditPriority,
        saveRequestChanges,
        reloadLatestForEdit,
    } = useActions(featureRequestsLogic)
    const editErrors = showEditFormErrors ? editFormErrors : {}

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
                        onClick={saveRequestChanges}
                        loading={savingRequestChanges}
                        disabledReason={editDisabledReason}
                        data-attr="save-feature-request-changes"
                    >
                        Save changes
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
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
                    <LemonField.Pure
                        label="Status"
                        help={activeRequest?.github_link ? 'Changing the status pauses GitHub sync.' : undefined}
                    >
                        <LemonSelect<FeatureRequestStatusEnumApi>
                            value={editStatus}
                            onChange={setEditStatus}
                            options={FEATURE_REQUEST_STATUS_OPTIONS}
                            fullWidth
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Priority">
                        <LemonSelect<FeatureRequestPriorityEnumApi | 'none'>
                            value={editPriority ?? 'none'}
                            onChange={(value) => setEditPriority(value === 'none' ? null : value)}
                            options={[{ value: 'none', label: 'No priority' }, ...FEATURE_REQUEST_PRIORITY_OPTIONS]}
                            fullWidth
                        />
                    </LemonField.Pure>
                </div>
                <LemonField.Pure label="Title" error={editErrors.title}>
                    <LemonInput value={editTitle} onChange={setEditTitle} maxLength={400} fullWidth />
                </LemonField.Pure>
                <LemonField.Pure label="Description" showOptional>
                    <LemonTextArea value={editDescription} onChange={setEditDescription} minRows={5} />
                </LemonField.Pure>
                <LemonField.Pure label="Accounts" error={editErrors.accounts}>
                    <LemonInputSelect
                        mode="multiple"
                        value={editAccountIds}
                        onChange={setEditAccountIds}
                        onInputChange={setAccountSearch}
                        options={accountOptions}
                        placeholder="Search for accounts"
                        loading={accountsLoading}
                        fullWidth
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Product areas" error={editErrors.productAreas}>
                    <LemonInputSelect
                        mode="multiple"
                        value={editProductAreaIds}
                        onChange={setEditProductAreaIds}
                        options={editProductAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
