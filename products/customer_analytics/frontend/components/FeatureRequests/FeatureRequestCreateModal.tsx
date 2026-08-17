import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonLabel,
    LemonModal,
    LemonTextArea,
} from '@posthog/lemon-ui'

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
    } = useValues(featureRequestsLogic)
    const {
        closeCreateRequest,
        setTitle,
        setDescription,
        setAccountId,
        setAccountSearch,
        setProductAreaIds,
        submitRequest,
        loadAccounts,
        loadProductAreas,
    } = useActions(featureRequestsLogic)

    return (
        <LemonModal
            isOpen={createRequestOpen}
            onClose={closeCreateRequest}
            title="New feature request"
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeCreateRequest}>
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
                <div className="flex flex-col gap-1">
                    <LemonLabel>Title</LemonLabel>
                    <LemonInput
                        value={title}
                        onChange={setTitle}
                        placeholder="What does the customer need?"
                        maxLength={400}
                        autoFocus
                        fullWidth
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Description</LemonLabel>
                    <LemonTextArea
                        value={description}
                        onChange={setDescription}
                        placeholder="Describe the request in the customer's language"
                        minRows={5}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Account</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        value={accountId ? [accountId] : []}
                        onChange={(values) => setAccountId(values[0] ?? null)}
                        onInputChange={setAccountSearch}
                        options={accountOptions}
                        placeholder="Search for an account"
                        loading={accountsLoading}
                        fullWidth
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>Product areas</LemonLabel>
                    <LemonInputSelect
                        mode="multiple"
                        value={productAreaIds}
                        onChange={setProductAreaIds}
                        options={productAreaOptions}
                        placeholder="Select one or more product areas"
                        loading={productAreasLoading}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
