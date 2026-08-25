import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonSelect,
    LemonTextArea,
} from '@posthog/lemon-ui'

import type { FeatureRequestStatusEnumApi, RequestPriorityEnumApi } from '../../generated/api.schemas'
import { FEATURE_REQUEST_PRIORITY_OPTIONS, FEATURE_REQUEST_STATUS_OPTIONS } from './featureRequestOptions'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestEditModal(): JSX.Element {
    const {
        editRequestOpen,
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
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Status</LemonLabel>
                        <LemonSelect<FeatureRequestStatusEnumApi>
                            value={editStatus}
                            onChange={setEditStatus}
                            options={FEATURE_REQUEST_STATUS_OPTIONS}
                            fullWidth
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Priority</LemonLabel>
                        <LemonSelect<RequestPriorityEnumApi | 'none'>
                            value={editPriority ?? 'none'}
                            onChange={(value) => setEditPriority(value === 'none' ? null : value)}
                            options={[{ value: 'none', label: 'No priority' }, ...FEATURE_REQUEST_PRIORITY_OPTIONS]}
                            fullWidth
                        />
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Title</LemonLabel>
                    <LemonInput value={editTitle} onChange={setEditTitle} maxLength={400} fullWidth />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Description (optional)</LemonLabel>
                    <LemonTextArea value={editDescription} onChange={setEditDescription} minRows={5} />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Accounts</LemonLabel>
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
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Product areas</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        value={editProductAreaIds}
                        onChange={setEditProductAreaIds}
                        options={editProductAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
