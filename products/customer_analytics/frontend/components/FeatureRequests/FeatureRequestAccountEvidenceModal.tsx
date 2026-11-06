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

import { dayjs } from 'lib/dayjs'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { FeatureRequestEvidenceImagePicker } from './FeatureRequestEvidenceImagePicker'
import { FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS } from './featureRequestEvidenceOptions'
import { featureRequestsLogic } from './featureRequestsLogic'

export function FeatureRequestAccountEvidenceModal(): JSX.Element {
    const {
        evidenceModalOpen,
        addingAccount,
        addAccountId,
        addAccountOptions,
        accountsLoading,
        accountsError,
        editingEvidenceId,
        evidenceSummary,
        evidenceQuote,
        evidenceSource,
        evidenceUrl,
        evidenceRequestedOn,
        evidenceError,
        savingEvidence,
        uploadingEvidenceImages,
        evidenceSaveDisabledReason,
    } = useValues(featureRequestsLogic)
    const {
        closeEvidence,
        setAddAccountId,
        setAccountSearch,
        loadAccounts,
        setEvidenceSummary,
        setEvidenceQuote,
        setEvidenceSource,
        setEvidenceUrl,
        setEvidenceRequestedOn,
        saveEvidence,
        removeEvidence,
    } = useActions(featureRequestsLogic)

    return (
        <LemonModal
            isOpen={evidenceModalOpen}
            onClose={() => {
                if (!uploadingEvidenceImages) {
                    closeEvidence()
                }
            }}
            title={addingAccount ? 'Add account and evidence' : editingEvidenceId ? 'Edit evidence' : 'Add evidence'}
            width={560}
            footer={
                <>
                    {editingEvidenceId && !addingAccount && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Remove evidence?',
                                    description:
                                        'This removes the evidence from the account. The change remains in request history.',
                                    primaryButton: {
                                        status: 'danger',
                                        children: 'Remove',
                                        onClick: removeEvidence,
                                    },
                                    secondaryButton: { children: 'Cancel' },
                                })
                            }
                            loading={savingEvidence}
                            disabledReason={uploadingEvidenceImages ? 'Uploading images' : undefined}
                            className="mr-auto"
                        >
                            Remove evidence
                        </LemonButton>
                    )}
                    <LemonButton
                        type="secondary"
                        onClick={closeEvidence}
                        disabledReason={uploadingEvidenceImages ? 'Uploading images' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveEvidence}
                        loading={savingEvidence}
                        disabledReason={evidenceSaveDisabledReason}
                        data-attr={addingAccount ? 'save-feature-request-account' : 'save-feature-request-evidence'}
                    >
                        {addingAccount ? 'Add account' : 'Save evidence'}
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                {accountsError && addingAccount && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadAccounts('') }}>
                        {accountsError}
                    </LemonBanner>
                )}
                {evidenceError && <LemonBanner type="error">{evidenceError}</LemonBanner>}
                {addingAccount && (
                    <>
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Account</LemonLabel>
                            <LemonInputSelect
                                mode="single"
                                value={addAccountId ? [addAccountId] : []}
                                onChange={(values) => setAddAccountId(values[0] ?? null)}
                                onInputChange={setAccountSearch}
                                options={addAccountOptions}
                                placeholder="Search by account name or external key"
                                loading={accountsLoading}
                                fullWidth
                            />
                        </div>
                        <div className="font-medium">Evidence (optional)</div>
                    </>
                )}
                <div className="flex flex-col gap-1">
                    <LemonLabel>Summary</LemonLabel>
                    <LemonTextArea
                        value={evidenceSummary}
                        onChange={setEvidenceSummary}
                        placeholder="Summarize what this account needs"
                        minRows={3}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Customer quote</LemonLabel>
                    <LemonTextArea
                        value={evidenceQuote}
                        onChange={setEvidenceQuote}
                        placeholder="Add the customer's words"
                        minRows={3}
                    />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Source</LemonLabel>
                        <LemonSelect
                            value={evidenceSource}
                            onChange={setEvidenceSource}
                            options={FEATURE_REQUEST_EVIDENCE_SOURCE_OPTIONS}
                            fullWidth
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Request date</LemonLabel>
                        <LemonCalendarSelectInput
                            value={evidenceRequestedOn ? dayjs(evidenceRequestedOn) : null}
                            onChange={(value) => setEvidenceRequestedOn(value?.format('YYYY-MM-DD') ?? null)}
                            selectionPeriod="past"
                            granularity="day"
                            clearable
                            placeholder="Select a date"
                        />
                    </div>
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Source URL</LemonLabel>
                    <LemonInput
                        type="url"
                        value={evidenceUrl}
                        onChange={setEvidenceUrl}
                        placeholder="https://example.com/source"
                        fullWidth
                    />
                </div>
                <FeatureRequestEvidenceImagePicker />
            </div>
        </LemonModal>
    )
}
