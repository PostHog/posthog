import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInputSelect, LemonLabel, LemonModal, Spinner } from '@posthog/lemon-ui'

import { TAG_REFERENCE_WARNING, tagsLogic } from './tagsLogic'

export function MergeTagModal(): JSX.Element | null {
    const {
        tagToMerge,
        target,
        destinations,
        destinationPage,
        destinationPageLoading,
        destinationError,
        preview,
        previewLoading,
        previewError,
        canSubmitMerge,
        mutationLoading,
        mutationError,
    } = useValues(tagsLogic)
    const { closeModals, setTarget, setDestinationSearch, retryDestinations, loadMoreDestinations, submitMerge } =
        useActions(tagsLogic)
    if (!tagToMerge) {
        return null
    }
    const options =
        target && !destinations.some((tag) => tag.id === target.id) ? [target, ...destinations] : destinations
    return (
        <LemonModal
            title={`Merge tag "${tagToMerge.name}"`}
            isOpen
            className="ph-no-capture"
            onClose={closeModals}
            closable={!mutationLoading}
            width="40rem"
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModals}
                        disabledReason={mutationLoading ? 'Wait for the merge to finish.' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        status="danger"
                        onClick={submitMerge}
                        loading={mutationLoading}
                        disabledReason={!canSubmitMerge ? 'Choose a destination and wait for the preview.' : undefined}
                        data-attr="tag-management-merge-confirm"
                    >
                        Merge tags
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <p>Move this tag's assignments into an existing tag, then remove this tag. This cannot be undone.</p>
                <div>
                    <LemonLabel htmlFor="merge-tag-destination">Destination tag</LemonLabel>
                    <LemonInputSelect
                        id="merge-tag-destination"
                        mode="single"
                        value={target ? [target.id] : []}
                        options={options.map((tag) => ({ key: tag.id, label: tag.name }))}
                        onChange={(ids) => setTarget(options.find((tag) => tag.id === ids[0]) ?? null)}
                        onInputChange={setDestinationSearch}
                        disableFiltering
                        allowCustomValues={false}
                        loading={destinationPageLoading}
                        disabled={mutationLoading}
                        placeholder="Search existing tags"
                        popoverClassName="ph-no-capture"
                        data-attr="tag-management-merge-destination"
                    />
                </div>
                {destinationPage?.next && !destinationError && (
                    <LemonButton onClick={loadMoreDestinations} loading={destinationPageLoading}>
                        Load more tags
                    </LemonButton>
                )}
                {destinationError && (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: retryDestinations }}>
                        {destinationError}
                    </LemonBanner>
                )}
                {previewLoading ? (
                    <Spinner />
                ) : previewError ? (
                    <LemonBanner type="error">{previewError}</LemonBanner>
                ) : preview && target && preview.tag.id === target.id ? (
                    <LemonBanner type="info">
                        <p>{`${preview.source_count} source assignments + ${preview.target_count} destination assignments - ${preview.overlap_count} overlaps = ${preview.result_count} assignments after merge.`}</p>
                    </LemonBanner>
                ) : null}
                <LemonBanner type="warning">{TAG_REFERENCE_WARNING}</LemonBanner>
                {mutationError && <LemonBanner type="error">{mutationError}</LemonBanner>}
            </div>
        </LemonModal>
    )
}
