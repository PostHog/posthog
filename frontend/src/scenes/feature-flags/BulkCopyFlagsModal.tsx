import { useActions, useValues } from 'kea'

import { IconCheck, IconWarning, IconX } from '@posthog/icons'
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

import { BULK_COPY_MAX_TARGET_PROJECTS, BulkCopyFailure, flagSelectionLogic } from './flagSelectionLogic'

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

    if (!bulkCopyModalVisible || !bulkCopyParams) {
        return null
    }

    const teams = [...(currentOrganization?.teams ?? [])].sort((a, b) => a.name.localeCompare(b.name))
    const teamNameById = new Map(teams.map((team) => [team.id, team.name]))
    const destinationOptions = teams
        .filter((team) => team.id !== bulkCopySourceProjectId)
        .map((team) => ({ key: String(team.id), label: team.name, value: team.id }))

    const pendingApproval = bulkCopyResult?.failed.filter((failure) => failure.approvalPending) ?? []
    const hardFailures = bulkCopyResult?.failed.filter((failure) => !failure.approvalPending) ?? []
    // Split copies into freshly created flags and overwrites of flags that already existed in the target
    const newCopies = (bulkCopyResult?.copied ?? [])
        .map((entry) => ({
            key: entry.key,
            projectIds: entry.projectIds.filter((id) => !entry.updatedProjectIds.includes(id)),
        }))
        .filter((entry) => entry.projectIds.length > 0)
    const overwrites = (bulkCopyResult?.copied ?? [])
        .map((entry) => ({ key: entry.key, projectIds: entry.updatedProjectIds }))
        .filter((entry) => entry.projectIds.length > 0)

    const submitDisabledReason =
        bulkCopyTargetProjectIds.length === 0
            ? 'Select at least one destination project'
            : bulkCopyTargetProjectIds.length > BULK_COPY_MAX_TARGET_PROJECTS
              ? `Bulk copy supports up to ${BULK_COPY_MAX_TARGET_PROJECTS} destination projects at once`
              : undefined

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
                            disabledReason={submitDisabledReason}
                            data-attr="bulk-copy-flags-submit"
                        >
                            {bulkCopyRunning && bulkCopyProgress
                                ? `Copying ${bulkCopyProgress.done} of ${bulkCopyProgress.total}…`
                                : 'Copy flags'}
                        </LemonButton>
                    </>
                )
            }
        >
            {bulkCopyResult ? (
                <div className="space-y-4">
                    {newCopies.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-success font-medium">
                                <IconCheck className="text-lg" />
                                <span>Copied {pluralize(newCopies.length, 'new flag')}</span>
                            </div>
                            <CopiedFlagsList entries={newCopies} teamNameById={teamNameById} />
                        </div>
                    )}
                    {overwrites.length > 0 && (
                        <div className="space-y-2">
                            <div className="flex items-center gap-2 text-warning font-medium">
                                <IconWarning className="text-lg" />
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
                                <IconWarning className="text-lg" />
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
                                <IconX className="text-lg" />
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
                    <p className="mb-0">
                        Copy the selected {pluralize(bulkCopyFlagCount, 'flag', 'flags', false)}{' '}
                        {bulkCopyFlagCount === 1 ? 'and its' : 'and their'} configuration to other projects in your
                        organization.
                    </p>
                    <LemonBanner type="warning">
                        If a flag with the same key already exists in a destination project, it will be overwritten with
                        the copied configuration. Flags referencing static cohorts get an empty copy of the cohort if
                        none with the same name exists in the destination, since its persons might not exist there.
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
