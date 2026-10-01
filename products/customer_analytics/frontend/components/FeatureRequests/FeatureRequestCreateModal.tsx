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

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { FeatureRequestEvidenceImagePicker } from './FeatureRequestEvidenceImagePicker'
import { FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS } from './featureRequestEvidenceOptions'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestCreateModal(): JSX.Element {
    const {
        createRequestOpen,
        title,
        description,
        accountId,
        productAreaIds,
        accountOptions,
        productAreaOptions,
        accountsLoading,
        accountsError,
        productAreasLoading,
        productAreasError,
        submittingRequest,
        submitDisabledReason,
        createFormErrors,
        showCreateFormErrors,
        evidenceSummary,
        evidenceQuote,
        evidenceSource,
        evidenceUrl,
        evidenceRequestedOn,
        uploadingEvidenceImages,
    } = useValues(featureRequestsLogic)
    const {
        closeCreateRequest,
        setTitle,
        setDescription,
        setAccountId,
        setAccountSearch,
        setProductAreaIds,
        setEvidenceSummary,
        setEvidenceQuote,
        setEvidenceSource,
        setEvidenceUrl,
        setEvidenceRequestedOn,
        submitRequest,
        loadAccounts,
        loadProductAreas,
    } = useActions(featureRequestsLogic)
    const createErrors = showCreateFormErrors ? createFormErrors : {}

    return (
        <LemonModal
            isOpen={createRequestOpen}
            onClose={() => {
                if (!uploadingEvidenceImages) {
                    closeCreateRequest()
                }
            }}
            title="New feature request"
            width={640}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeCreateRequest}
                        disabledReason={uploadingEvidenceImages ? 'Uploading images' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitRequest}
                        loading={submittingRequest}
                        disabledReason={submitDisabledReason}
                        data-attr="save-feature-request"
                    >
                        Save request
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {accountsError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadAccounts('') }}>
                        {accountsError}
                    </LemonBanner>
                )}
                {productAreasError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadProductAreas }}>
                        {productAreasError}
                    </LemonBanner>
                )}
                <LemonField.Pure label="Title" error={createErrors.title}>
                    <LemonInput
                        value={title}
                        onChange={setTitle}
                        placeholder="What does the customer need?"
                        maxLength={400}
                        autoFocus
                        fullWidth
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Description" showOptional>
                    <LemonTextArea
                        value={description}
                        onChange={setDescription}
                        placeholder="Describe the request in the customer's language"
                        minRows={5}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Account" error={createErrors.accounts}>
                    <LemonInputSelect
                        mode="single"
                        value={accountId ? [accountId] : []}
                        onChange={(values) => setAccountId(values[0] ?? null)}
                        onInputChange={setAccountSearch}
                        options={accountOptions}
                        placeholder="Search by account name or external key"
                        loading={accountsLoading}
                        fullWidth
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Product areas" error={createErrors.productAreas}>
                    <LemonInputSelect
                        mode="multiple"
                        value={productAreaIds}
                        onChange={setProductAreaIds}
                        options={productAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </LemonField.Pure>
                <div className="font-medium">Evidence (optional)</div>
                <LemonField.Pure label="Summary">
                    <LemonTextArea
                        value={evidenceSummary}
                        onChange={setEvidenceSummary}
                        placeholder="Summarize what this account needs"
                        minRows={3}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Customer quote">
                    <LemonTextArea
                        value={evidenceQuote}
                        onChange={setEvidenceQuote}
                        placeholder="Add the customer's words"
                        minRows={3}
                    />
                </LemonField.Pure>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <LemonField.Pure label="Source">
                        <LemonSelect
                            value={evidenceSource}
                            onChange={setEvidenceSource}
                            options={FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS}
                            fullWidth
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Request date">
                        <LemonCalendarSelectInput
                            value={evidenceRequestedOn ? dayjs(evidenceRequestedOn) : null}
                            onChange={(value) => setEvidenceRequestedOn(value?.format('YYYY-MM-DD') ?? null)}
                            selectionPeriod="past"
                            granularity="day"
                            clearable
                            placeholder="Select a date"
                        />
                    </LemonField.Pure>
                </div>
                <LemonField.Pure label="Source URL">
                    <LemonInput
                        type="url"
                        value={evidenceUrl}
                        onChange={setEvidenceUrl}
                        placeholder="https://example.com/source"
                        fullWidth
                    />
                </LemonField.Pure>
                <FeatureRequestEvidenceImagePicker />
            </div>
        </LemonModal>
    )
}
