import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheck, IconCopy, IconWarning, IconX } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTag,
} from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'

import { BulkCopyFailure, flagSelectionLogic, getBulkCopyDisabledReason } from './flagSelectionLogic'

/** "Copy to projects" bulk action button shared by the flags overview table and the projects grid. */
export function BulkCopyToProjectsButton({
    dataAttr,
    selectedCount,
    extraDisabledReason,
    onOpen,
}: {
    dataAttr: string
    selectedCount: number
    extraDisabledReason?: string | null
    onOpen: () => void
}): JSX.Element {
    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconCopy />}
            data-attr={dataAttr}
            disabledReason={getBulkCopyDisabledReason(selectedCount, extraDisabledReason)}
            onClick={onOpen}
        >
            Copy to projects
        </LemonButton>
    )
}

function CopiedFlagsList({
    entries,
    teamNameById,
}: {
    entries: Array<{ key: string; projectIds: number[] }>
    teamNameById: Map<number, string>
}): JSX.Element {
    return (
        <ul className="list-none pl-6 space-y-1">
            {entries.map((entry) => (
                <li key={entry.key} className="text-sm">
                    <span className="font-medium">{entry.key}</span>
                    <span className="text-muted">
                        {' → '}
                        {entry.projectIds.map((id) => teamNameById.get(id) ?? `Project ${id}`).join(', ')}
                    </span>
                </li>
            ))}
        </ul>
    )
}

function FailureList({
    failures,
    teamNameById,
}: {
    failures: BulkCopyFailure[]
    teamNameById: Map<number, string>
}): JSX.Element {
    return (
        <ul className="list-none pl-6 space-y-1">
            {failures.map((failure, index) => (
                <li key={`${failure.key}-${failure.projectId}-${index}`} className="text-sm">
                    <span className="font-medium">{failure.key}</span>
                    <span className="text-muted">
                        {' → '}
                        {failure.projectId !== null
                            ? (teamNameById.get(failure.projectId) ?? `Project ${failure.projectId}`)
                            : 'unknown project'}
                    </span>
                    <span className="text-muted-alt"> — {failure.errorMessage}</span>
                </li>
            ))}
        </ul>
    )
}

export function BulkCopyFlagsModal(): JSX.Element | null {
    const {
        bulkCopyModalVisible,
        bulkCopyParams,
        bulkCopySourceProjectId,
        bulkCopyTargetProjectIds,
        bulkCopySchedule,
        bulkCopyDisableCopiedFlag,
        bulkCopyRunning,
        bulkCopyProgress,
        bulkCopyResult,
        bulkCopyFlagCount,
        bulkCopySplitCopied,
        bulkCopyPendingApproval: pendingApproval,
        bulkCopyHardFailures: hardFailures,
        bulkCopySubmitDisabledReason,
    } = useValues(flagSelectionLogic)
    const {
        closeBulkCopyModal,
        setBulkCopySourceProjectId,
        setBulkCopyTargetProjectIds,
        setBulkCopySchedule,
        setBulkCopyDisableCopiedFlag,
        bulkCopyFlags,
    } = useActions(flagSelectionLogic)
    const { currentOrganization } = useValues(organizationLogic)

    // Gate the sort on visibility (rather than skipping the hook) so it doesn't redo this work
    // on every render of the parent scene while the modal is closed.
    const teams = useMemo(
        () =>
            bulkCopyModalVisible
                ? [...(currentOrganization?.teams ?? [])].sort((a, b) => a.name.localeCompare(b.name))
                : [],
        [bulkCopyModalVisible, currentOrganization?.teams]
    )
    const teamNameById = useMemo(() => new Map(teams.map((team) => [team.id, team.name])), [teams])
    const destinationOptions = useMemo(
        () =>
            teams
                .filter((team) => team.id !== bulkCopySourceProjectId)
                .map((team) => ({ key: String(team.id), label: team.name, value: team.id })),
        [teams, bulkCopySourceProjectId]
    )

    if (!bulkCopyModalVisible || !bulkCopyParams) {
        return null
    }

    const { newCopies, overwrites } = bulkCopySplitCopied
    const progressText =
        bulkCopyRunning && bulkCopyProgress ? `Copying ${bulkCopyProgress.done} of ${bulkCopyProgress.total}` : null

    return (
        <LemonModal
            isOpen={bulkCopyModalVisible}
            onClose={() => {
                if (!bulkCopyRunning) {
                    closeBulkCopyModal()
                }
            }}
            title={bulkCopyResult ? 'Copy results' : `Copy ${pluralize(bulkCopyFlagCount, 'flag')} to other projects`}
            width={600}
            footer={
                bulkCopyResult ? (
                    <LemonButton type="primary" onClick={closeBulkCopyModal} data-attr="bulk-copy-flags-done">
                        Done
                    </LemonButton>
                ) : (
                    <>
                        <LemonButton
                            type="secondary"
                            onClick={closeBulkCopyModal}
                            disabledReason={bulkCopyRunning ? 'Copy in progress' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={bulkCopyFlags}
                            loading={bulkCopyRunning}
                            disabledReason={bulkCopySubmitDisabledReason}
                            data-attr="bulk-copy-flags-submit"
                        >
                            {progressText ? `${progressText}…` : 'Copy flags'}
                        </LemonButton>
                        <span aria-live="polite" aria-atomic="true" className="sr-only">
                            {progressText ?? ''}
                        </span>
                    </>
                )
            }
        >
            {bulkCopyResult ? (
                <div className="space-y-4">
                    {newCopies.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-success font-medium">
                                <IconCheck className="text-lg" aria-hidden="true" />
                                <span>Copied {pluralize(newCopies.length, 'new flag')}</span>
                            </div>
                            <CopiedFlagsList entries={newCopies} teamNameById={teamNameById} />
                        </div>
                    )}
                    {overwrites.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-warning font-medium">
                                <IconWarning className="text-lg" aria-hidden="true" />
                                <span>Updated {pluralize(overwrites.length, 'existing flag')}</span>
                            </div>
                            <p className="text-sm text-muted pl-6 mb-0">
                                These flags already existed in the destination project and were overwritten with the
                                copied configuration.
                            </p>
                            <CopiedFlagsList entries={overwrites} teamNameById={teamNameById} />
                        </div>
                    )}
                    {pendingApproval.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-warning font-medium">
                                <IconWarning className="text-lg" aria-hidden="true" />
                                <span>
                                    {pluralize(pendingApproval.length, 'copy', 'copies')} pending approval
                                    <LemonTag type="warning" className="ml-2 uppercase">
                                        Not applied yet
                                    </LemonTag>
                                </span>
                            </div>
                            <p className="text-sm text-muted pl-6 mb-0">
                                These projects require approval for flag changes. A change request was created for each
                                and the copy will apply once approved.
                            </p>
                            <FailureList failures={pendingApproval} teamNameById={teamNameById} />
                        </div>
                    )}
                    {hardFailures.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-danger font-medium">
                                <IconX className="text-lg" aria-hidden="true" />
                                <span>{pluralize(hardFailures.length, 'copy', 'copies')} failed</span>
                            </div>
                            <FailureList failures={hardFailures} teamNameById={teamNameById} />
                        </div>
                    )}
                    {bulkCopyResult.skippedFlagCount > 0 && (
                        <p className="text-sm text-muted mb-0">
                            {pluralize(bulkCopyResult.skippedFlagCount, 'selected flag')} could not be resolved and{' '}
                            {bulkCopyResult.skippedFlagCount === 1 ? 'was' : 'were'} skipped — possibly deleted since
                            selection.
                        </p>
                    )}
                    {bulkCopyResult.warnings.length > 0 && (
                        <LemonBanner type="warning">
                            <div className="space-y-1">
                                {bulkCopyResult.warnings.map((warning) => (
                                    <div key={warning} className="text-sm">
                                        {warning}
                                    </div>
                                ))}
                            </div>
                        </LemonBanner>
                    )}
                </div>
            ) : (
                <div className="space-y-4">
                    <LemonBanner type="warning">
                        <ul className="list-disc pl-4 space-y-1">
                            <li>If a flag with the same key exists in a destination, it will be overwritten.</li>
                            <li>
                                If your flag uses a static cohort, it will get an empty cohort if a cohort with the same
                                name does not exist in the destination.
                            </li>
                        </ul>
                    </LemonBanner>
                    {bulkCopyParams.sourceSelectable && (
                        <div className="space-y-1">
                            <div className="font-semibold">Source project</div>
                            <LemonSelect
                                value={bulkCopySourceProjectId}
                                onChange={(id) => id !== null && setBulkCopySourceProjectId(id)}
                                options={teams.map((team) => ({ value: team.id, label: team.name }))}
                                dropdownMatchSelectWidth={false}
                                data-attr="bulk-copy-flags-source"
                            />
                            <p className="text-sm text-muted mb-0">
                                Flags that don't exist in the source project are skipped and reported.
                            </p>
                        </div>
                    )}
                    <div className="space-y-1">
                        <div className="font-semibold">Destination projects</div>
                        <LemonInputSelect<number>
                            mode="multiple"
                            value={bulkCopyTargetProjectIds}
                            onChange={setBulkCopyTargetProjectIds}
                            options={destinationOptions}
                            placeholder="Select projects to copy to"
                            disabled={bulkCopyRunning}
                            data-attr="bulk-copy-flags-destinations"
                        />
                    </div>
                    <LemonCheckbox
                        checked={bulkCopySchedule}
                        onChange={setBulkCopySchedule}
                        disabled={bulkCopyRunning}
                        label="Copy pending scheduled changes"
                        data-attr="bulk-copy-flags-schedule"
                    />
                    <LemonCheckbox
                        checked={bulkCopyDisableCopiedFlag}
                        onChange={setBulkCopyDisableCopiedFlag}
                        disabled={bulkCopyRunning}
                        label="Copy as disabled"
                        data-attr="bulk-copy-flags-disable"
                    />
                    {bulkCopyDisableCopiedFlag && (
                        <p className="text-sm text-muted mb-0">
                            Copied flags will be disabled in the destination projects regardless of their status here —
                            useful when staging config shouldn't go live in production immediately.
                        </p>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
