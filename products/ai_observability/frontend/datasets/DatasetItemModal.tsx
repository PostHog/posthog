import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React from 'react'

import {
    LemonBanner,
    LemonButton,
    LemonCollapse,
    LemonDivider,
    LemonLabel,
    LemonModal,
    LemonSkeleton,
    LemonTag,
} from '@posthog/lemon-ui'

import type { ApiError } from 'lib/api-error'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'

import { JSONEditor } from '../components/JSONEditor'
import type { DatasetItemReadApi } from '../generated/api.schemas'
import type { DatasetItemModalValue } from './datasetItemModalLogic'
import { DatasetItemModalLogicProps, datasetItemModalLogic, isStoredDatasetItem } from './datasetItemModalLogic'
import { prettifyJson } from './utils'

export interface DatasetItemModalProps {
    isOpen: boolean
    onClose: (refetchDatasetItems?: boolean) => void
    datasetId: string
    partialDatasetItem?: DatasetItemModalValue | null
    /**
     * Whether the modal should display the "Save and add another" button.
     */
    displayBulkCreationButton?: boolean
    title?: string
    readOnly?: boolean
    readOnlyReason?: string
    loading?: boolean
    loadError?: ApiError | null
    versions?: DatasetItemReadApi[]
    versionsLoading?: boolean
    versionsLoadError?: ApiError | null
    versionsCount?: number
    versionsPage?: number
    versionsPageSize?: number
    canRestoreVersions?: boolean
    restoringVersion?: number | null
    onRestoreVersion?: (version: number) => void
    onVersionsPageChange?: (page: number) => void
    onRetryVersions?: () => void
    onRetry?: () => void
    onUnarchive?: () => void
    unarchiving?: boolean
}

export const DatasetItemModal = React.memo(function DatasetItemModal({
    isOpen,
    onClose,
    partialDatasetItem,
    datasetId,
    displayBulkCreationButton,
    title,
    readOnly = false,
    readOnlyReason,
    loading = false,
    loadError,
    versions = [],
    versionsLoading = false,
    versionsLoadError,
    versionsCount = 0,
    versionsPage = 1,
    versionsPageSize = 25,
    canRestoreVersions = false,
    restoringVersion,
    onRestoreVersion,
    onVersionsPageChange,
    onRetryVersions,
    onRetry,
    onUnarchive,
    unarchiving = false,
}: DatasetItemModalProps): JSX.Element {
    const logicProps: DatasetItemModalLogicProps = {
        datasetId,
        partialDatasetItem,
        closeModal: onClose,
        isModalOpen: isOpen,
        readOnly,
        restoringVersion,
    }
    const {
        datasetItemFormSubmitDisabledReason,
        datasetItemVersionRestoreDisabledReason,
        isDatasetItemFormReadOnly,
        isDatasetItemFormSubmitting,
        refetchDatasetItems,
    } = useValues(datasetItemModalLogic(logicProps))
    const { submitDatasetItemForm, setShouldCloseModal } = useActions(datasetItemModalLogic(logicProps))
    const storedDatasetItem = isStoredDatasetItem(partialDatasetItem) ? partialDatasetItem : null

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => onClose(refetchDatasetItems)}
            maxWidth="56rem"
            simple
            className="w-full"
        >
            <Form
                logic={datasetItemModalLogic}
                props={logicProps}
                formKey="datasetItemForm"
                enableFormOnSubmit={!isDatasetItemFormReadOnly}
                className="flex flex-col overflow-y-hidden"
            >
                <LemonModalHeader>
                    <div className="flex items-center gap-2">
                        <h3>
                            {title ??
                                (storedDatasetItem
                                    ? readOnly
                                        ? 'Dataset item'
                                        : 'Edit dataset item'
                                    : loading || loadError
                                      ? 'Dataset item'
                                      : 'New dataset item')}
                        </h3>
                        {storedDatasetItem?.archived && <LemonTag type="muted">Archived</LemonTag>}
                        {storedDatasetItem && (
                            <LemonTag type="default">Revision {storedDatasetItem.dataset_revision}</LemonTag>
                        )}
                    </div>
                </LemonModalHeader>

                <LemonModalContent className="flex flex-col gap-4">
                    {loadError ? (
                        <LemonBanner
                            type="error"
                            action={
                                onRetry && loadError.status !== 403 && loadError.status !== 404
                                    ? { children: 'Try again', onClick: onRetry }
                                    : undefined
                            }
                        >
                            {getDatasetItemLoadErrorMessage(loadError)}
                        </LemonBanner>
                    ) : loading && !partialDatasetItem ? (
                        <div className="flex flex-col gap-2">
                            <LemonSkeleton active className="h-24 w-full" />
                            <LemonSkeleton active className="h-24 w-full" />
                        </div>
                    ) : (
                        <>
                            {readOnlyReason && <LemonBanner type="info">{readOnlyReason}</LemonBanner>}
                            <LemonField name="input" label="Input">
                                <JSONEditor readOnly={isDatasetItemFormReadOnly} />
                            </LemonField>
                            <LemonField name="expectedOutput" label="Expected output" showOptional>
                                <JSONEditor readOnly={isDatasetItemFormReadOnly} />
                            </LemonField>
                            {partialDatasetItem?.source_output !== undefined &&
                                partialDatasetItem.source_output !== null && (
                                    <div>
                                        <LemonLabel>Source output</LemonLabel>
                                        <JSONEditor
                                            value={prettifyJson(partialDatasetItem.source_output) ?? ''}
                                            readOnly
                                        />
                                    </div>
                                )}
                            <LemonField name="metadata" label="Metadata">
                                <JSONEditor readOnly={isDatasetItemFormReadOnly} />
                            </LemonField>
                            {storedDatasetItem && (
                                <>
                                    <LemonDivider />
                                    <DatasetItemHistory
                                        currentItem={storedDatasetItem}
                                        versions={versions}
                                        loading={versionsLoading}
                                        loadError={versionsLoadError}
                                        count={versionsCount}
                                        page={versionsPage}
                                        pageSize={versionsPageSize}
                                        canRestore={canRestoreVersions}
                                        restoringVersion={restoringVersion}
                                        restoreDisabledReason={datasetItemVersionRestoreDisabledReason}
                                        onRestore={onRestoreVersion}
                                        onPageChange={onVersionsPageChange}
                                        onRetry={onRetryVersions}
                                    />
                                </>
                            )}
                        </>
                    )}
                </LemonModalContent>

                <LemonModalFooter>
                    {readOnly || loadError || loading ? (
                        <>
                            <LemonButton type="secondary" onClick={() => onClose(refetchDatasetItems)}>
                                Close
                            </LemonButton>
                            {onUnarchive && storedDatasetItem?.archived && (
                                <LemonButton type="primary" onClick={onUnarchive} loading={unarchiving}>
                                    Unarchive
                                </LemonButton>
                            )}
                        </>
                    ) : (
                        <>
                            {displayBulkCreationButton && !storedDatasetItem && (
                                <LemonButton
                                    type="secondary"
                                    loading={isDatasetItemFormSubmitting}
                                    disabledReason={datasetItemFormSubmitDisabledReason}
                                    htmlType="submit"
                                    onClick={(e) => {
                                        e.preventDefault()
                                        setShouldCloseModal(false)
                                        submitDatasetItemForm()
                                    }}
                                >
                                    Save and add another
                                </LemonButton>
                            )}
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isDatasetItemFormSubmitting}
                                disabledReason={datasetItemFormSubmitDisabledReason}
                            >
                                Save
                            </LemonButton>
                        </>
                    )}
                </LemonModalFooter>
            </Form>
        </LemonModal>
    )
})

function DatasetItemHistory({
    currentItem,
    versions,
    loading,
    loadError,
    count,
    page,
    pageSize,
    canRestore,
    restoringVersion,
    restoreDisabledReason,
    onRestore,
    onPageChange,
    onRetry,
}: {
    currentItem: DatasetItemReadApi
    versions: DatasetItemReadApi[]
    loading: boolean
    loadError?: ApiError | null
    count: number
    page: number
    pageSize: number
    canRestore: boolean
    restoringVersion?: number | null
    restoreDisabledReason?: string
    onRestore?: (version: number) => void
    onPageChange?: (page: number) => void
    onRetry?: () => void
}): JSX.Element {
    if (loading) {
        return <LemonSkeleton active className="h-16 w-full" />
    }

    if (loadError) {
        return (
            <LemonBanner type="error" action={onRetry ? { children: 'Try again', onClick: onRetry } : undefined}>
                {loadError.detail || "Couldn't load item history. Try again."}
            </LemonBanner>
        )
    }

    const pageCount = Math.ceil(count / pageSize)
    const pageStart = (page - 1) * pageSize + 1
    const pageEnd = Math.min(page * pageSize, count)

    return (
        <div className="flex flex-col gap-2">
            <h4 className="m-0">Item history</h4>
            {versions.length === 0 ? (
                <p className="text-muted m-0">No item history is available.</p>
            ) : (
                <LemonCollapse
                    embedded
                    size="small"
                    panels={versions.map((version) => ({
                        key: version.version,
                        header: (
                            <div className="flex flex-wrap items-center gap-2 text-left">
                                <strong>Version {version.version}</strong>
                                <span className="text-muted">Revision {version.dataset_revision}</span>
                                <LemonTag type={version.archived ? 'muted' : 'success'}>
                                    {version.archived ? 'Archived' : 'Active'}
                                </LemonTag>
                                <TZLabel time={version.version_created_at} />
                                <span className="text-muted">
                                    {version.version_created_by?.email ?? 'Unknown creator'}
                                </span>
                            </div>
                        ),
                        content: (
                            <div className="flex flex-col gap-3 p-3">
                                <DatasetItemVersionValue label="Input" value={version.input} />
                                <DatasetItemVersionValue label="Expected output" value={version.expected_output} />
                                <DatasetItemVersionValue label="Source output" value={version.source_output} />
                                <DatasetItemVersionValue label="Metadata" value={version.metadata} />
                                {canRestore && version.version !== currentItem.version && onRestore && (
                                    <div>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => onRestore(version.version)}
                                            loading={restoringVersion === version.version}
                                            disabledReason={
                                                restoreDisabledReason ??
                                                (restoringVersion && restoringVersion !== version.version
                                                    ? 'Another version is being restored'
                                                    : undefined)
                                            }
                                        >
                                            Restore this version
                                        </LemonButton>
                                    </div>
                                )}
                            </div>
                        ),
                    }))}
                />
            )}
            {pageCount > 1 && onPageChange && (
                <div className="flex items-center justify-between gap-2">
                    <span className="text-muted">
                        {pageStart}-{pageEnd} of {count} versions
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => onPageChange(page - 1)}
                            disabledReason={page <= 1 ? 'No previous page' : undefined}
                        >
                            Previous
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={() => onPageChange(page + 1)}
                            disabledReason={page >= pageCount ? 'No next page' : undefined}
                        >
                            Next
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}

function DatasetItemVersionValue({ label, value }: { label: string; value: unknown }): JSX.Element {
    return (
        <div>
            <LemonLabel>{label}</LemonLabel>
            <JSONEditor value={prettifyJson(value) ?? 'null'} readOnly />
        </div>
    )
}

function getDatasetItemLoadErrorMessage(error: ApiError): string {
    if (error.status === 404) {
        return 'This dataset item was not found. Close this dialog and choose another item.'
    }
    if (error.status === 403) {
        return "You don't have permission to view this dataset item."
    }
    return error.detail || "Couldn't load this dataset item. Try again."
}
