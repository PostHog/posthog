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

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { FeatureRequestEvidenceImagePicker } from './FeatureRequestEvidenceImagePicker'
import { FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS } from './featureRequestEvidenceOptions'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestCreateModal(): JSX.Element {
    const {
        createRequestOpen,
        accountOptions,
        productAreaOptions,
        accountsLoading,
        accountsError,
        productAreasLoading,
        productAreasError,
        isFeatureRequestFormSubmitting,
        evidenceSummary,
        evidenceQuote,
        evidenceSource,
        evidenceUrl,
        evidenceRequestedOn,
        uploadingEvidenceImages,
    } = useValues(featureRequestsLogic)
    const {
        closeCreateRequest,
        setAccountSearch,
        setEvidenceSummary,
        setEvidenceQuote,
        setEvidenceSource,
        setEvidenceUrl,
        setEvidenceRequestedOn,
        submitFeatureRequestForm,
        loadAccounts,
        loadProductAreas,
    } = useActions(featureRequestsLogic)

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
                        onClick={submitFeatureRequestForm}
                        loading={isFeatureRequestFormSubmitting}
                        disabledReason={uploadingEvidenceImages ? 'Uploading images' : undefined}
                        data-attr="save-feature-request"
                    >
                        Save request
                    </LemonButton>
                </>
            }
        >
            <Form logic={featureRequestsLogic} formKey="featureRequestForm" className="flex flex-col gap-4">
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
                <LemonField name="title" label="Title">
                    <LemonInput placeholder="What does the customer need?" maxLength={400} autoFocus fullWidth />
                </LemonField>
                <LemonField name="description" label="Description" showOptional>
                    <LemonTextArea placeholder="Describe the request in the customer's language" minRows={5} />
                </LemonField>
                <LemonField name="accountId" label="Account">
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="single"
                            value={value ? [value] : []}
                            onChange={(values) => onChange(values[0] ?? null)}
                            onInputChange={setAccountSearch}
                            options={accountOptions}
                            placeholder="Search by account name or external key"
                            loading={accountsLoading}
                            fullWidth
                        />
                    )}
                </LemonField>
                <LemonField name="productAreaIds" label="Product areas">
                    <LemonInputSelect
                        mode="multiple"
                        options={productAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </LemonField>
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
            </Form>
        </LemonModal>
    )
}
