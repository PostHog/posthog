import { IconEllipsis, IconTrash } from '@posthog/icons'
import { useState } from 'react'
import { IconSort } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { SettingsBar, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { LemonModal, LemonInput, LemonButton } from '@posthog/lemon-ui'

import { RecordingUniversalFilters } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const SortingKeyToLabel = {
    start_time: 'Latest',
    activity_score: 'Activity',
    console_error_count: 'Errors',
    duration: 'Total duration',
    active_seconds: 'Activity',
    inactive_seconds: 'Inactivity',
    click_count: 'Clicks',
    keypress_count: 'Keystrokes',
    mouse_activity_count: 'Mouse activity',
}

function SortedBy({
    filters,
    setFilters,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    return (
        <SettingsMenu
            highlightWhenActive={false}
            items={[
                {
                    label: SortingKeyToLabel['start_time'],
                    onClick: () => setFilters({ order: 'start_time' }),
                    active: filters.order === 'start_time',
                },
                {
                    label: SortingKeyToLabel['activity_score'],
                    onClick: () => setFilters({ order: 'activity_score' }),
                    active: filters.order === 'activity_score',
                },
                {
                    label: SortingKeyToLabel['console_error_count'],
                    onClick: () => setFilters({ order: 'console_error_count' }),
                    active: filters.order === 'console_error_count',
                },
                {
                    label: 'Longest',
                    items: [
                        {
                            label: SortingKeyToLabel['duration'],
                            onClick: () => setFilters({ order: 'duration' }),
                            active: filters.order === 'duration',
                        },
                        {
                            label: SortingKeyToLabel['active_seconds'],
                            onClick: () => setFilters({ order: 'active_seconds' }),
                            active: filters.order === 'active_seconds',
                        },
                        {
                            label: SortingKeyToLabel['inactive_seconds'],
                            onClick: () => setFilters({ order: 'inactive_seconds' }),
                            active: filters.order === 'inactive_seconds',
                        },
                    ],
                },
                {
                    label: 'Most active',
                    items: [
                        {
                            label: SortingKeyToLabel['click_count'],
                            onClick: () => setFilters({ order: 'click_count' }),
                            active: filters.order === 'click_count',
                        },
                        {
                            label: SortingKeyToLabel['keypress_count'],
                            onClick: () => setFilters({ order: 'keypress_count' }),
                            active: filters.order === 'keypress_count',
                        },
                        {
                            label: SortingKeyToLabel['mouse_activity_count'],
                            onClick: () => setFilters({ order: 'mouse_activity_count' }),
                            active: filters.order === 'mouse_activity_count',
                        },
                    ],
                },
            ]}
            icon={<IconSort className="text-lg" />}
            label={SortingKeyToLabel[filters.order || 'start_time']}
        />
    )
}

export function SessionRecordingsPlaylistTopSettings({
    filters,
    setFilters,
    onDelete,
}: {
    filters?: RecordingUniversalFilters
    setFilters?: (filters: Partial<RecordingUniversalFilters>) => void
    onDelete?: (filters: Partial<RecordingUniversalFilters>) => void
}): JSX.Element {
    const { autoplayDirection } = useValues(playerSettingsLogic)
    const { setAutoplayDirection } = useActions(playerSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false)
    const [confirmationText, setConfirmationText] = useState('')
    const confirmationTextPattern = 'Delete recordings'

    const handleBulkDeleteRecordings = (): void => {
        setConfirmationText('') // Reset confirmation text
        setIsDeleteDialogOpen(true)
    }

    const menuItems = [
        {
            label: 'Autoplay',
            items: [
                {
                    label: 'Off',
                    onClick: () => setAutoplayDirection(null),
                    active: !autoplayDirection,
                },
                {
                    label: 'Newer recordings',
                    onClick: () => setAutoplayDirection('newer'),
                    active: autoplayDirection === 'newer',
                },
                {
                    label: 'Older recordings',
                    onClick: () => setAutoplayDirection('older'),
                    active: autoplayDirection === 'older',
                },
            ],
        },
        ...(featureFlags[FEATURE_FLAGS.REPLAY_BULK_DELETE_RECORDINGS]
            ? [
                  {
                      label: 'Delete recordings',
                      onClick: () => handleBulkDeleteRecordings(),
                      status: 'danger' as const,
                      icon: <IconTrash />,
                  },
              ]
            : []),
    ]

    return (
        <SettingsBar border="none" className="justify-between">
            {filters && setFilters ? (
                <span className="text-xs font-normal inline-flex items-center ml-2">
                    Sort by: <SortedBy filters={filters} setFilters={setFilters} />
                </span>
            ) : null}
            <SettingsMenu items={menuItems} icon={<IconEllipsis className="rotate-90" />} />

            {/* Add the controlled dialog */}
            <LemonModal
                isOpen={isDeleteDialogOpen}
                onClose={() => setIsDeleteDialogOpen(false)}
                title="Confirm deletion"
                maxWidth="500px"
            >
                <div className="space-y-4">
                    <h4>Are you sure you want to delete all recordings matching these filters?</h4>
                    <div className="space-y-2">
                        <label className="text-sm">
                            To confirm, please type <strong>{confirmationTextPattern}</strong> below:
                        </label>
                        <LemonInput
                            value={confirmationText}
                            onChange={setConfirmationText}
                            placeholder={confirmationTextPattern}
                            className="w-full"
                            autoFocus
                        />
                    </div>
                    <div className="bg-warning-highlight border border-warning rounded p-2 text-sm">
                        This action cannot be undone. Deleting recordings won't affect your billing since we charge for
                        ingestion, not storage.
                    </div>
                </div>
                <div className="flex justify-end gap-2 mt-4">
                    <LemonButton type="secondary" onClick={() => setIsDeleteDialogOpen(false)}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            confirmationText !== confirmationTextPattern
                                ? 'Please type the correct confirmation text'
                                : undefined
                        }
                        onClick={() => {
                            onDelete?.(filters || {})
                            setIsDeleteDialogOpen(false)
                        }}
                    >
                        Delete
                    </LemonButton>
                </div>
            </LemonModal>
        </SettingsBar>
    )
}
