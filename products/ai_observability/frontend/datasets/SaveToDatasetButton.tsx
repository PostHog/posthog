import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React, { useMemo } from 'react'

import { IconDatabase, IconExternal, IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'
import { isObject } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { DatasetItemCreateApi } from '../generated/api.schemas'
import { DatasetItemModal } from './DatasetItemModal'
import { saveToDatasetButtonLogic } from './saveToDatasetButtonLogic'
import { useKeyboardNavigation } from './useKeyboardNavigation'
import { normalizeJsonValue } from './utils'

export interface SaveToDatasetButtonProps {
    traceId: string
    timestamp: string
    sourceId: string
    input?: unknown
    output?: unknown
    metadata?: unknown
}

export const SaveToDatasetButton = React.memo(function SaveToDatasetButton({
    traceId,
    timestamp,
    sourceId,
    input,
    output,
    metadata,
}: SaveToDatasetButtonProps): JSX.Element {
    const partialDatasetItem: Partial<DatasetItemCreateApi> = useMemo(
        () => ({
            client_item_id: sourceId,
            source_trace_id: traceId,
            source_timestamp: timestamp,
            source_event_id: sourceId,
            input: normalizeJsonValue(input ?? {}, {}) ?? {},
            source_output: normalizeJsonValue(output, null),
            metadata: toMetadataObject(metadata),
        }),
        [traceId, timestamp, sourceId, input, output, metadata]
    )
    const logic = saveToDatasetButtonLogic({ partialDatasetItem })

    const { dropdownVisible, isModalOpen, selectedDataset, isModalMounted } = useValues(logic)
    const { setEditMode, setDropdownVisible, setIsModalOpen } = useActions(logic)

    return (
        <>
            <LemonDropdown
                overlay={<OverlayMenu />}
                visible={dropdownVisible}
                onVisibilityChange={setDropdownVisible}
                closeOnClickInside={false}
            >
                <AccessControlAction
                    resourceType={AccessControlResourceType.LlmAnalytics}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        icon={<IconDatabase />}
                        sideAction={{
                            icon: <IconPencil />,
                            onClick: () => {
                                if (!dropdownVisible) {
                                    setEditMode('edit')
                                }
                                setDropdownVisible(!dropdownVisible)
                            },
                            tooltip: 'Add to dataset and edit it',
                        }}
                        onClick={() => {
                            setDropdownVisible(!dropdownVisible)
                        }}
                    >
                        Add to dataset
                    </LemonButton>
                </AccessControlAction>
            </LemonDropdown>
            {isModalMounted && selectedDataset && (
                <DatasetItemModal
                    isOpen={isModalOpen}
                    onClose={() => setIsModalOpen(false)}
                    datasetId={selectedDataset.id}
                    partialDatasetItem={partialDatasetItem}
                    title={`New dataset item for ${selectedDataset.name}`}
                />
            )}
        </>
    )
})

function OverlayMenu(): JSX.Element {
    const { datasets, isLoadingDatasets, isSearchFormSubmitting, recentDatasets, searchForm } =
        useValues(saveToDatasetButtonLogic)
    const { setSearchFormValue, setDropdownVisible } = useActions(saveToDatasetButtonLogic)

    const { referenceRef, itemsRef, focusedItemIndex } = useKeyboardNavigation<HTMLDivElement, HTMLButtonElement>(
        (datasets?.length ?? 0) + (recentDatasets?.length ?? 0),
        0,
        { enabled: !isLoadingDatasets && !isSearchFormSubmitting }
    )

    const recentDatasetsLength = recentDatasets?.length ?? 0

    return (
        <Form logic={saveToDatasetButtonLogic} formKey="searchForm" className="w-xs" enableFormOnSubmit>
            <LemonField name="search" label="Search" labelClassName="sr-only">
                <LemonInput placeholder="Find a dataset" autoFocus />
            </LemonField>
            <LemonDivider className="my-0 mt-2" />
            <div
                className={clsx('overflow-y-auto max-h-64 py-2', isLoadingDatasets ? 'space-y-4' : 'space-y-2')}
                ref={referenceRef}
            >
                {isLoadingDatasets ? (
                    <>
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                        <LemonSkeleton active className="h-4 w-full" />
                    </>
                ) : datasets && datasets.length > 0 ? (
                    <>
                        {!searchForm.search && recentDatasets.length > 0 && (
                            <>
                                <p className="text-muted text-xs px-2">Recent datasets</p>
                                {recentDatasets.map((dataset, index) => (
                                    <AccessControlAction
                                        key={dataset.id}
                                        ref={itemsRef?.current?.[index]}
                                        resourceType={AccessControlResourceType.LlmAnalytics}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={toAccessControlLevel(dataset.user_access_level)}
                                    >
                                        <LemonButton
                                            fullWidth
                                            size="small"
                                            active={focusedItemIndex === index}
                                            htmlType="submit"
                                            onClick={() => {
                                                setSearchFormValue('datasetId', dataset.id)
                                            }}
                                            loading={isSearchFormSubmitting && searchForm.datasetId === dataset.id}
                                            disabledReason={
                                                isSearchFormSubmitting && searchForm.datasetId !== dataset.id
                                                    ? 'A dataset item is being saved'
                                                    : undefined
                                            }
                                            data-attr="save-to-dataset-select"
                                        >
                                            <span className="line-clamp-1">{dataset.name}</span>
                                        </LemonButton>
                                    </AccessControlAction>
                                ))}
                                <LemonDivider className="my-0 mb-2" />
                            </>
                        )}
                        {datasets.map((dataset, index) => (
                            <AccessControlAction
                                key={dataset.id}
                                ref={itemsRef?.current?.[recentDatasetsLength + index]}
                                resourceType={AccessControlResourceType.LlmAnalytics}
                                minAccessLevel={AccessControlLevel.Editor}
                                userAccessLevel={toAccessControlLevel(dataset.user_access_level)}
                            >
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    active={focusedItemIndex - recentDatasetsLength === index}
                                    htmlType="submit"
                                    onClick={() => {
                                        setSearchFormValue('datasetId', dataset.id)
                                    }}
                                    loading={isSearchFormSubmitting && searchForm.datasetId === dataset.id}
                                    disabledReason={
                                        isSearchFormSubmitting && searchForm.datasetId !== dataset.id
                                            ? 'A dataset item is being saved'
                                            : undefined
                                    }
                                    data-attr="save-to-dataset-select"
                                >
                                    <span className="line-clamp-1">{dataset.name}</span>
                                </LemonButton>
                            </AccessControlAction>
                        ))}
                    </>
                ) : (
                    <p className="text-muted text-sm px-2">No datasets found</p>
                )}
            </div>
            <LemonDivider className="my-0 mb-2" />
            <LemonButton
                fullWidth
                size="small"
                to={urls.aiObservabilityDataset('new')}
                sideIcon={<IconExternal />}
                targetBlank
                onClick={() => {
                    setDropdownVisible(false)
                }}
            >
                Create new dataset
            </LemonButton>
        </Form>
    )
}

function toMetadataObject(metadata: unknown): Record<string, unknown> {
    if (metadata === null || metadata === undefined) {
        return {}
    }

    if (isObject(metadata) && !Array.isArray(metadata)) {
        return metadata
    }

    return { value: metadata }
}
