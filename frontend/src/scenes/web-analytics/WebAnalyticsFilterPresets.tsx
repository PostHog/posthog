import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    IconBookmark,
    IconBookmarkSolid,
    IconCheck,
    IconPin,
    IconPinFilled,
    IconPlus,
    IconTrash,
    IconX,
} from '@posthog/icons'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonModal,
    LemonSkeleton,
    LemonTextArea,
    Popover,
} from '@posthog/lemon-ui'

import { WebAnalyticsFilterPresetType } from '~/types'

import { webAnalyticsFilterPresetsLogic } from './webAnalyticsFilterPresetsLogic'

export const FilterPresetsDropdown = (): JSX.Element => {
    const [dropdownOpen, setDropdownOpen] = useState(false)
    const { pinnedPresets, recentPresets, presetsLoading, activePreset, hasPresets, presetToDelete } =
        useValues(webAnalyticsFilterPresetsLogic)
    const { applyPreset, deletePreset, updatePreset, openSaveModal, clearPreset, openDeleteModal, closeDeleteModal } =
        useActions(webAnalyticsFilterPresetsLogic)

    const handleTogglePin = (preset: WebAnalyticsFilterPresetType, e: React.MouseEvent): void => {
        e.stopPropagation()
        updatePreset(preset.short_id, { pinned: !preset.pinned })
    }

    const handleDelete = (preset: WebAnalyticsFilterPresetType, e: React.MouseEvent): void => {
        e.stopPropagation()
        setDropdownOpen(false)
        openDeleteModal(preset)
    }

    const renderPresetItem = (preset: WebAnalyticsFilterPresetType): JSX.Element => {
        const isActive = activePreset?.short_id === preset.short_id

        return (
            <div
                key={preset.short_id}
                className="flex items-center justify-between gap-2 px-2 py-1.5 hover:bg-bg-light rounded cursor-pointer group"
                onClick={() => {
                    applyPreset(preset)
                    setDropdownOpen(false)
                }}
            >
                <div className="flex items-center gap-2 flex-1 min-w-0">
                    {isActive && <IconCheck className="text-success shrink-0 text-base" />}
                    <div className="flex-1 min-w-0">
                        <div className="text-sm font-medium truncate">{preset.name}</div>
                        {preset.description && <div className="text-xs text-muted truncate">{preset.description}</div>}
                    </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <LemonButton
                        size="xsmall"
                        icon={preset.pinned ? <IconPinFilled /> : <IconPin />}
                        onClick={(e) => handleTogglePin(preset, e)}
                        tooltip={preset.pinned ? 'Unpin' : 'Pin'}
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconTrash />}
                        onClick={(e) => handleDelete(preset, e)}
                        tooltip="Delete"
                        status="danger"
                    />
                </div>
            </div>
        )
    }

    const dropdownContent = (
        <div className="w-72 max-h-96 overflow-y-auto">
            <div className="p-2">
                <LemonButton
                    fullWidth
                    size="small"
                    icon={<IconPlus />}
                    onClick={() => {
                        setDropdownOpen(false)
                        openSaveModal()
                    }}
                >
                    Save current filters
                </LemonButton>
            </div>

            {presetsLoading ? (
                <div className="p-3 space-y-2">
                    <LemonSkeleton className="h-8" />
                    <LemonSkeleton className="h-8" />
                </div>
            ) : !hasPresets ? (
                <div className="px-3 pb-3 text-center text-muted text-sm">
                    No saved presets yet.
                    <br />
                    Save your current filters to create one.
                </div>
            ) : (
                <>
                    {pinnedPresets.length > 0 && (
                        <>
                            <LemonDivider />
                            <div className="px-2 py-1">
                                <div className="text-xs font-semibold text-muted uppercase px-2 py-1">Pinned</div>
                                {pinnedPresets.map(renderPresetItem)}
                            </div>
                        </>
                    )}

                    {recentPresets.length > 0 && (
                        <>
                            <LemonDivider />
                            <div className="px-2 py-1">
                                <div className="text-xs font-semibold text-muted uppercase px-2 py-1">Recent</div>
                                {recentPresets.map(renderPresetItem)}
                            </div>
                        </>
                    )}
                </>
            )}
        </div>
    )

    const bookmarkIcon = activePreset ? <IconBookmarkSolid className="text-yellow-400" /> : <IconBookmark />
    return (
        <>
            <Popover
                visible={dropdownOpen}
                onClickOutside={() => setDropdownOpen(false)}
                placement="bottom-start"
                fallbackPlacements={['bottom-end']}
                overlay={dropdownContent}
            >
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={bookmarkIcon}
                    onClick={() => setDropdownOpen(!dropdownOpen)}
                    data-attr="web-analytics-filter-presets"
                    active={!!activePreset}
                    sideAction={
                        activePreset
                            ? {
                                  icon: <IconX />,
                                  tooltip: 'Clear preset',
                                  onClick: (e) => {
                                      e.stopPropagation()
                                      clearPreset()
                                  },
                              }
                            : undefined
                    }
                >
                    {activePreset ? <span className="max-w-32 truncate">{activePreset.name}</span> : 'Presets'}
                </LemonButton>
            </Popover>
            <SaveFilterPresetModal />
            <DeletePresetModal
                preset={presetToDelete}
                onClose={closeDeleteModal}
                onConfirm={() => presetToDelete && deletePreset(presetToDelete)}
            />
        </>
    )
}

const SaveFilterPresetModal = (): JSX.Element | null => {
    const { saveModalOpen, savedPresetLoading, presetFormName, presetFormDescription, canSavePreset } =
        useValues(webAnalyticsFilterPresetsLogic)
    const { closeSaveModal, saveCurrentFiltersAsPreset, setPresetFormName, setPresetFormDescription } =
        useActions(webAnalyticsFilterPresetsLogic)

    const handleSave = (): void => {
        if (canSavePreset) {
            saveCurrentFiltersAsPreset(presetFormName.trim(), presetFormDescription.trim() || undefined)
        }
    }

    return (
        <LemonModal
            isOpen={saveModalOpen}
            onClose={closeSaveModal}
            title="Save filter preset"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSaveModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSave}
                        loading={savedPresetLoading}
                        disabledReason={!canSavePreset ? 'Name is required' : undefined}
                    >
                        Save preset
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="text-sm font-medium mb-1 block">Name</label>
                    <LemonInput
                        value={presetFormName}
                        onChange={setPresetFormName}
                        placeholder="e.g., US Mobile Traffic"
                        autoFocus
                    />
                </div>
                <div>
                    <label className="text-sm font-medium mb-1 block">Description (optional)</label>
                    <LemonTextArea
                        value={presetFormDescription}
                        onChange={setPresetFormDescription}
                        placeholder="Describe what this preset filters for..."
                        rows={2}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

const DeletePresetModal = ({
    preset,
    onClose,
    onConfirm,
}: {
    preset: WebAnalyticsFilterPresetType | null
    onClose: () => void
    onConfirm: () => void
}): JSX.Element => {
    return (
        <LemonModal
            isOpen={!!preset}
            onClose={onClose}
            title={`Delete "${preset?.name}"?`}
            description="This preset will be permanently deleted."
            overlayClassName="!items-center"
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" status="danger" onClick={onConfirm}>
                        Delete
                    </LemonButton>
                </>
            }
        />
    )
}
