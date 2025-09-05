import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconBookmark, IconFilter, IconPlusSmall, IconShare, IconTrash } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumn, lemonToast } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import { DataTableNode } from '~/queries/schema/schema-general'

import { DataTableSavedFilter, dataTableSavedFiltersLogic } from './dataTableSavedFiltersLogic'

export interface DataTableSavedFiltersProps {
    uniqueKey: string
    query: DataTableNode
    setQuery: (query: DataTableNode) => void
}

export function DataTableSavedFilters({ uniqueKey, query, setQuery }: DataTableSavedFiltersProps): JSX.Element | null {
    const logic = dataTableSavedFiltersLogic({ uniqueKey, query, setQuery })
    const { savedFilters, appliedSavedFilter, hasUnsavedFilterChanges, showSavedFilters } = useValues(logic)
    const { applySavedFilter, deleteSavedFilter, createSavedFilter, updateSavedFilter, setAppliedSavedFilter } =
        useActions(logic)

    const [isSaveModalOpen, setIsSaveModalOpen] = useState(false)
    const [saveFilterName, setSaveFilterName] = useState('')

    if (!showSavedFilters) {
        return null
    }

    const handleSaveFilter = (): void => {
        if (saveFilterName.trim()) {
            createSavedFilter(saveFilterName.trim())
            setIsSaveModalOpen(false)
            setSaveFilterName('')
            lemonToast.success(`Saved filter "${saveFilterName.trim()}"`)
        }
    }

    const handleUpdateFilter = (): void => {
        if (appliedSavedFilter) {
            updateSavedFilter(appliedSavedFilter.id, { query })
            lemonToast.success(`Updated filter "${appliedSavedFilter.name}"`)
        }
    }

    const handleShareFilter = (filter: DataTableSavedFilter): void => {
        // Apply the filter first to ensure URL is updated with correct parameters
        applySavedFilter(filter)

        // Use the current URL which already contains all filter parameters
        const url = window.location.href

        navigator.clipboard.writeText(url).then(() => {
            lemonToast.success('Filter link copied to clipboard!')
        })
    }

    const columns: LemonTableColumn<DataTableSavedFilter, keyof DataTableSavedFilter | undefined>[] = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, filter) => (
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={() => applySavedFilter(filter)}
                    className="text-left"
                    fullWidth
                >
                    <div className="flex items-center gap-2">
                        {appliedSavedFilter?.id === filter.id && <IconBookmark className="text-primary" />}
                        <span className={appliedSavedFilter?.id === filter.id ? 'font-bold' : ''}>{filter.name}</span>
                    </div>
                </LemonButton>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'createdAt',
            width: 150,
            render: (createdAt) => <TZLabel time={createdAt as string} />,
        },
        {
            title: 'Actions',
            width: 150,
            render: (_, filter) => (
                <div className="flex gap-2 justify-end">
                    <Tooltip title="Apply filter">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconFilter />}
                            onClick={() => applySavedFilter(filter)}
                        />
                    </Tooltip>
                    <Tooltip title="Share filter">
                        <LemonButton
                            type="tertiary"
                            size="small"
                            icon={<IconShare />}
                            onClick={() => handleShareFilter(filter)}
                        />
                    </Tooltip>
                    <Tooltip title="Delete filter">
                        <LemonButton
                            type="tertiary"
                            status="danger"
                            size="small"
                            icon={<IconTrash />}
                            onClick={() => {
                                deleteSavedFilter(filter.id)
                                if (appliedSavedFilter?.id === filter.id) {
                                    setAppliedSavedFilter(null)
                                }
                                lemonToast.success(`Deleted filter "${filter.name}"`)
                            }}
                        />
                    </Tooltip>
                </div>
            ),
        },
    ]

    return (
        <>
            <div className="border rounded-lg p-4 bg-bg-light">
                <div className="space-y-4">
                    <div className="flex justify-between items-center">
                        <div className="text-sm font-medium">Saved Filters</div>
                        <div className="flex gap-2">
                            {appliedSavedFilter && hasUnsavedFilterChanges && (
                                <>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={handleUpdateFilter}
                                        tooltip="Update the current saved filter with your changes"
                                    >
                                        Update "{appliedSavedFilter.name}"
                                    </LemonButton>
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconPlusSmall />}
                                        onClick={() => setIsSaveModalOpen(true)}
                                    >
                                        Save as new
                                    </LemonButton>
                                </>
                            )}
                            {(!appliedSavedFilter || !hasUnsavedFilterChanges) && (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconPlusSmall />}
                                    onClick={() => setIsSaveModalOpen(true)}
                                >
                                    Save current filters
                                </LemonButton>
                            )}
                        </div>
                    </div>

                    {savedFilters.length === 0 ? (
                        <div className="flex flex-col items-center justify-center py-8 border rounded-lg bg-bg-light">
                            <IconBookmark className="text-4xl text-muted mb-4" />
                            <h3 className="text-lg font-medium mb-2">No saved filters yet</h3>
                            <p className="text-muted text-center max-w-md">
                                Save your frequently used filter combinations to quickly access them later
                            </p>
                        </div>
                    ) : (
                        <LemonTable dataSource={savedFilters} columns={columns} size="small" />
                    )}
                </div>
            </div>

            <LemonModal
                title="Save filters"
                isOpen={isSaveModalOpen}
                onClose={() => {
                    setIsSaveModalOpen(false)
                    setSaveFilterName('')
                }}
                footer={
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={() => {
                                setIsSaveModalOpen(false)
                                setSaveFilterName('')
                            }}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={handleSaveFilter}
                            disabledReason={!saveFilterName.trim() ? 'Please enter a name' : undefined}
                        >
                            Save filter
                        </LemonButton>
                    </>
                }
            >
                <div className="space-y-4">
                    <p className="text-muted">Give your filter combination a name to easily access it later</p>
                    <LemonInput
                        value={saveFilterName}
                        onChange={setSaveFilterName}
                        placeholder="e.g., Last 7 days completed events"
                        autoFocus
                        onPressEnter={handleSaveFilter}
                    />
                </div>
            </LemonModal>
        </>
    )
}
