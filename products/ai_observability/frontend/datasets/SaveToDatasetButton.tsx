import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import React from 'react'

import { IconDatabase, IconExternal, IconPencil } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonDropdown, LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { toAccessControlLevel } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DatasetItemModal } from './DatasetItemModal'
import { type StepReadFailure, saveToDatasetButtonLogic } from './saveToDatasetButtonLogic'
import type { TraceStep } from './traceStepDatasetItem'
import { useKeyboardNavigation } from './useKeyboardNavigation'

export interface SaveToDatasetButtonProps {
    step: TraceStep
}

const STEP_READ_FAILURE_MESSAGES: Record<StepReadFailure, string> = {
    error: "Couldn't load this step.",
    not_found: 'This step no longer exists.',
}

export const SaveToDatasetButton = React.memo(function SaveToDatasetButton({
    step,
}: SaveToDatasetButtonProps): JSX.Element {
    const logic = saveToDatasetButtonLogic({ step })

    const { dropdownVisible, isModalOpen, selectedDataset, isModalMounted, modalItem } = useValues(logic)
    const { setEditMode, setDropdownVisible, closeItemModal } = useActions(logic)

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
                        data-attr="save-to-dataset-open"
                        size="xsmall"
                        icon={<IconDatabase />}
                        sideAction={{
                            'data-attr': 'save-to-dataset-edit',
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
                    onClose={closeItemModal}
                    datasetId={selectedDataset.id}
                    partialDatasetItem={modalItem}
                    title={`New dataset item for ${selectedDataset.name}`}
                />
            )}
        </>
    )
})

function OverlayMenu(): JSX.Element {
    const { datasets, isLoadingDatasets, isSearchFormSubmitting, recentDatasets, searchForm, stepReadStatus } =
        useValues(saveToDatasetButtonLogic)
    const { setSearchFormValue, setDropdownVisible, retryStepRead } = useActions(saveToDatasetButtonLogic)

    const { referenceRef, itemsRef, focusedItemIndex } = useKeyboardNavigation<HTMLDivElement, HTMLButtonElement>(
        (datasets?.length ?? 0) + (recentDatasets?.length ?? 0),
        0,
        { enabled: !isLoadingDatasets && !isSearchFormSubmitting }
    )

    const recentDatasetsLength = recentDatasets?.length ?? 0
    const stepReadFailure = stepReadStatus === 'error' || stepReadStatus === 'not_found' ? stepReadStatus : null

    function getDatasetDisabledReason(datasetId: string): string | undefined {
        if (stepReadFailure) {
            return STEP_READ_FAILURE_MESSAGES[stepReadFailure]
        }
        return isSearchFormSubmitting && searchForm.datasetId !== datasetId
            ? 'A dataset item is being saved'
            : undefined
    }

    return (
        <Form logic={saveToDatasetButtonLogic} formKey="searchForm" className="w-xs" enableFormOnSubmit>
            <LemonField name="search" label="Search" labelClassName="sr-only">
                <LemonInput placeholder="Find a dataset" autoFocus data-attr="save-to-dataset-search" />
            </LemonField>
            <LemonDivider className="my-0 mt-2" />
            {stepReadFailure && (
                <LemonBanner
                    type="error"
                    className="mt-2"
                    action={
                        stepReadFailure === 'error'
                            ? {
                                  children: 'Try again',
                                  onClick: retryStepRead,
                                  'data-attr': 'save-to-dataset-step-retry',
                              }
                            : undefined
                    }
                >
                    {STEP_READ_FAILURE_MESSAGES[stepReadFailure]}
                </LemonBanner>
            )}
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
                                            disabledReason={getDatasetDisabledReason(dataset.id)}
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
                                    disabledReason={getDatasetDisabledReason(dataset.id)}
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
                data-attr="save-to-dataset-create"
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
