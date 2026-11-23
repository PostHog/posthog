import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Item,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { SessionRecordingTriggerGroup } from '~/lib/components/IngestionControls/types'

import { QuillCreateFromLegacyDialog } from './QuillCreateFromLegacyDialog'
import { QuillDeleteLastTriggerGroupDialog } from './QuillDeleteLastTriggerGroupDialog'
import { QuillTriggerGroupCard } from './QuillTriggerGroupCard'
import { QuillTriggerGroupForm } from './QuillTriggerGroupForm'
import { replayTriggersV2Logic } from './replayTriggersV2Logic'
import { confirmDeleteTriggerGroup, triggerGroupDisplayName } from './triggerGroupHelpers'

export function QuillTriggerGroupsEditor({ titleBadge }: { titleBadge?: ReactNode }): JSX.Element {
    const {
        triggerGroups,
        isAddingGroup,
        editingGroupId,
        deleteModalGroupId,
        showLegacyModal,
        previewLegacyGroups,
        _savingStateLoading,
        shouldShowMigrationBanner,
        hasLegacyTriggers,
    } = useValues(replayTriggersV2Logic)
    const {
        addTriggerGroup,
        updateTriggerGroup,
        deleteTriggerGroup,
        setIsAddingGroup,
        setEditingGroupId,
        setDeleteModalGroupId,
        showCreateFromLegacyModal,
        hideCreateFromLegacyModal,
        confirmCreateFromLegacy,
    } = useActions(replayTriggersV2Logic)

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const handleDeleteTriggerGroup = (id: string): void =>
        confirmDeleteTriggerGroup(triggerGroups, id, setDeleteModalGroupId, deleteTriggerGroup)

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Heading size="sm" render={<h3 className="m-0 flex items-center gap-1" />}>
                        Trigger groups
                        {titleBadge}
                    </Heading>
                    {!isAddingGroup && !editingGroupId && (
                        <div className="flex flex-wrap gap-2">
                            {hasLegacyTriggers && (
                                <Button
                                    variant="outline"
                                    onClick={showCreateFromLegacyModal}
                                    disabledReason={restrictedReason}
                                    data-attr="trigger-group-migrate-from-legacy"
                                >
                                    Migrate from legacy recording conditions
                                </Button>
                            )}
                            <Button
                                variant="primary"
                                onClick={() => setIsAddingGroup(true)}
                                disabledReason={restrictedReason}
                                data-attr="trigger-group-add"
                            >
                                <IconPlus />
                                Add
                            </Button>
                        </div>
                    )}
                </div>
                <Text size="xs" render={<p className="m-0" />}>
                    Configure custom recording triggers with individual sampling rates per group. Recording will start
                    if any of the recording trigger groups match.
                </Text>
            </div>

            {shouldShowMigrationBanner && (
                <Item tone="info" size="sm">
                    <ItemContent>
                        <ItemTitle>You're using legacy recording triggers</ItemTitle>
                        <ItemDescription>
                            Trigger groups offer more flexibility, including individual sampling rates per group.
                            Migrate your existing configuration by clicking the migrate button above.
                        </ItemDescription>
                    </ItemContent>
                </Item>
            )}

            {isAddingGroup && (
                <QuillTriggerGroupForm
                    onSave={(group) => {
                        addTriggerGroup(group)
                    }}
                    onCancel={() => setIsAddingGroup(false)}
                />
            )}

            {triggerGroups.length === 0 && !isAddingGroup ? (
                <Empty className="rounded-md border border-dashed border-border">
                    <EmptyHeader>
                        <EmptyTitle>No trigger groups configured</EmptyTitle>
                        <EmptyDescription>
                            {hasLegacyTriggers
                                ? 'Recording falls back to your legacy conditions below.'
                                : 'Add a group to start recording based on specific conditions.'}
                        </EmptyDescription>
                    </EmptyHeader>
                </Empty>
            ) : (
                <div className="flex flex-col gap-2">
                    {triggerGroups.map((group: SessionRecordingTriggerGroup, index: number) => (
                        <div key={group.id} className="flex flex-col gap-2">
                            {index > 0 && (
                                <Text
                                    size="xs"
                                    weight="semibold"
                                    variant="muted"
                                    render={<p className="m-0 text-center" />}
                                >
                                    OR
                                </Text>
                            )}
                            {editingGroupId === group.id ? (
                                <QuillTriggerGroupForm
                                    group={group}
                                    onSave={(updatedGroup) => {
                                        updateTriggerGroup(updatedGroup.id, updatedGroup)
                                    }}
                                    onCancel={() => setEditingGroupId(null)}
                                />
                            ) : (
                                <QuillTriggerGroupCard
                                    group={group}
                                    onEdit={() => setEditingGroupId(group.id)}
                                    onDelete={handleDeleteTriggerGroup}
                                />
                            )}
                        </div>
                    ))}
                </div>
            )}

            <QuillCreateFromLegacyDialog
                isOpen={showLegacyModal}
                onClose={hideCreateFromLegacyModal}
                onConfirm={confirmCreateFromLegacy}
                previewGroups={previewLegacyGroups}
                isCreating={_savingStateLoading}
            />

            <QuillDeleteLastTriggerGroupDialog
                isOpen={!!deleteModalGroupId}
                onClose={() => setDeleteModalGroupId(null)}
                onConfirm={() => {
                    if (deleteModalGroupId) {
                        deleteTriggerGroup(deleteModalGroupId)
                    }
                }}
                groupName={triggerGroupDisplayName(
                    triggerGroups.find((g) => g.id === deleteModalGroupId)?.name,
                    deleteModalGroupId
                )}
            />
        </div>
    )
}
