import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconPencil, IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'

import type { ExperimentPhase } from '~/types'

import { experimentLogic } from '../experimentLogic'

interface PhaseRow {
    index: number
    phase: ExperimentPhase
    isSynthetic?: boolean
    isNew?: boolean
}

interface EditingState {
    phaseIndex: number
    name: string
    reason: string
    startDate: string
    endDate: string | null
}

interface NewPhaseState {
    name: string
    reason: string
    startDate: string
}

function clonePhases(phases: ExperimentPhase[]): ExperimentPhase[] {
    return phases.map((phase) => ({ ...phase }))
}

function getPhaseName(phase: ExperimentPhase, index: number): string {
    return phase.name || `Phase ${index + 1}`
}

function validatePhases(phases: ExperimentPhase[], now: ReturnType<typeof dayjs> = dayjs()): string | null {
    if (!phases.length) {
        return null
    }

    for (let i = 0; i < phases.length; i++) {
        const phase = phases[i]
        const phaseName = getPhaseName(phase, i)
        const start = dayjs(phase.start_date)

        if (!start.isValid()) {
            return `${phaseName} has an invalid start date`
        }

        if (start.isAfter(now)) {
            return `${phaseName} cannot start in the future`
        }

        const previousPhase = phases[i - 1]
        if (previousPhase) {
            if (!previousPhase.end_date) {
                return `${getPhaseName(previousPhase, i - 1)} must have an end date`
            }
            if (!start.isSame(dayjs(previousPhase.end_date))) {
                return `${phaseName} must start when ${getPhaseName(previousPhase, i - 1)} ends`
            }
        }

        if (!phase.end_date) {
            if (i < phases.length - 1) {
                return `${phaseName} must have an end date`
            }
            continue
        }

        const end = dayjs(phase.end_date)
        if (!end.isValid()) {
            return `${phaseName} has an invalid end date`
        }

        if (end.isAfter(now)) {
            return `${phaseName} cannot end in the future`
        }

        if (!start.isBefore(end)) {
            return `${phaseName} must end after it starts`
        }
    }

    return null
}

function validateNewPhase(
    newPhaseStartDate: string,
    phases: ExperimentPhase[],
    experimentStartDate: string | null | undefined,
    hasPendingChanges: boolean,
    isEditing: boolean,
    now: ReturnType<typeof dayjs> = dayjs()
): string | undefined {
    if (hasPendingChanges) {
        return 'Save or discard pending phase edits before adding a new phase'
    }

    if (isEditing) {
        return 'Save or cancel the phase currently being edited'
    }

    const startDate = dayjs(newPhaseStartDate)
    if (!startDate.isValid()) {
        return 'Select a valid phase start date'
    }

    if (startDate.isAfter(now)) {
        return 'Phase start date cannot be in the future'
    }

    if (!experimentStartDate) {
        return 'Experiment must be running before adding phases'
    }

    if (!startDate.isAfter(dayjs(experimentStartDate))) {
        return 'Phase start date must be after the experiment start date'
    }

    const lastPhaseStartDate = phases.length ? phases[phases.length - 1].start_date : null
    if (lastPhaseStartDate && !startDate.isAfter(dayjs(lastPhaseStartDate))) {
        return 'Phase start date must be after the previous phase start date'
    }

    return undefined
}

function applyPhaseUpdates(
    phases: ExperimentPhase[],
    phaseIndex: number,
    updates: { name: string; reason: string; start_date: string; end_date: string | null }
): ExperimentPhase[] {
    const updatedPhases = clonePhases(phases)
    const phase = updatedPhases[phaseIndex]

    if (!phase) {
        return updatedPhases
    }

    phase.name = updates.name || undefined
    phase.reason = updates.reason || undefined
    phase.start_date = updates.start_date
    phase.end_date = updates.end_date

    if (phaseIndex > 0) {
        updatedPhases[phaseIndex - 1].end_date = updates.start_date
    }

    if (phaseIndex < updatedPhases.length - 1 && updates.end_date) {
        updatedPhases[phaseIndex + 1].start_date = updates.end_date
    }

    return updatedPhases
}

function DatePickerCell({
    value,
    onChange,
    calendarOpen,
    calendarKey,
    onOpenCalendar,
    onCloseCalendar,
    readOnlyText,
}: {
    value: string | null
    onChange: (value: string) => void
    calendarOpen: 'startDate' | 'endDate' | null
    calendarKey: 'startDate' | 'endDate'
    onOpenCalendar: (key: 'startDate' | 'endDate') => void
    onCloseCalendar: () => void
    readOnlyText?: string
}): JSX.Element {
    if (readOnlyText) {
        return <span className="text-secondary text-xs">{readOnlyText}</span>
    }

    return (
        <Popover
            actionable
            onClickOutside={onCloseCalendar}
            visible={calendarOpen === calendarKey}
            overlay={
                <LemonCalendarSelect
                    value={value ? dayjs(value) : dayjs()}
                    onChange={(v) => {
                        onChange(v.toISOString())
                        onCloseCalendar()
                    }}
                    onClose={onCloseCalendar}
                    granularity="minute"
                    selectionPeriod="past"
                />
            }
        >
            <LemonButton type="secondary" size="xsmall" onClick={() => onOpenCalendar(calendarKey)}>
                {value ? dayjs(value).format('MMM D, YYYY hh:mm A') : 'Select date'}
            </LemonButton>
        </Popover>
    )
}

export function EditPhasesModal(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { isEditPhasesModalOpen, experiment, selectedPhaseIndex } = useValues(experimentLogic)
    const { closeEditPhasesModal, addPhase, updateExperiment, refreshExperimentResults } = useActions(experimentLogic)

    const [baselinePhases, setBaselinePhases] = useState<ExperimentPhase[]>([])
    const [draftPhases, setDraftPhases] = useState<ExperimentPhase[]>([])
    const [editing, setEditing] = useState<EditingState | null>(null)
    const [addingNewPhase, setAddingNewPhase] = useState<NewPhaseState | null>(null)
    const [calendarOpen, setCalendarOpen] = useState<'startDate' | 'endDate' | null>(null)
    const [isSavingChanges, setIsSavingChanges] = useState(false)
    const hasOpenedModalRef = useRef(false)

    const isRunning = !!experiment.start_date && !experiment.end_date

    useEffect(() => {
        if (!isEditPhasesModalOpen) {
            hasOpenedModalRef.current = false
            setEditing(null)
            setAddingNewPhase(null)
            setCalendarOpen(null)
            setIsSavingChanges(false)
            return
        }

        if (hasOpenedModalRef.current) {
            return
        }

        hasOpenedModalRef.current = true
        const phases = clonePhases(experiment.phases || [])
        setBaselinePhases(phases)
        setDraftPhases(phases)
    }, [isEditPhasesModalOpen, experiment.phases, experiment.start_date])

    const draftPhasesJson = useMemo(() => JSON.stringify(draftPhases), [draftPhases])
    const baselinePhasesJson = useMemo(() => JSON.stringify(baselinePhases), [baselinePhases])
    const serverPhasesJson = useMemo(() => JSON.stringify(experiment.phases || []), [experiment.phases])

    // Keep in sync with server updates when there are no unsaved local edits.
    useEffect(() => {
        if (
            !isEditPhasesModalOpen ||
            draftPhasesJson !== baselinePhasesJson ||
            serverPhasesJson === baselinePhasesJson
        ) {
            return
        }

        const syncedPhases = clonePhases(experiment.phases || [])
        setBaselinePhases(syncedPhases)
        setDraftPhases(syncedPhases)
    }, [
        isEditPhasesModalOpen,
        draftPhasesJson,
        baselinePhasesJson,
        serverPhasesJson,
        experiment.phases,
        experiment.start_date,
    ])

    const hasPendingChanges = draftPhasesJson !== baselinePhasesJson

    const rows: PhaseRow[] = useMemo(() => {
        const baseRows: PhaseRow[] =
            draftPhases.length > 0
                ? draftPhases.map((phase, i) => ({
                      index: i + 1,
                      phase,
                  }))
                : experiment.start_date
                  ? [
                        {
                            index: 1,
                            phase: {
                                start_date: experiment.start_date,
                                end_date: experiment.end_date ?? null,
                                name: 'Phase 1',
                            },
                            isSynthetic: true,
                        },
                    ]
                  : []

        if (addingNewPhase) {
            baseRows.push({
                index: draftPhases.length + 1,
                phase: {
                    start_date: addingNewPhase.startDate,
                    end_date: null,
                    name: addingNewPhase.name || undefined,
                    reason: addingNewPhase.reason || undefined,
                },
                isNew: true,
            })
        }

        return baseRows
    }, [draftPhases, experiment.start_date, experiment.end_date, addingNewPhase])

    const startEditing = (row: PhaseRow): void => {
        if (row.isSynthetic || row.isNew) {
            return
        }

        const phase = row.phase
        setEditing({
            phaseIndex: row.index - 1,
            name: phase.name || '',
            reason: phase.reason || '',
            startDate: phase.start_date,
            endDate: phase.end_date ?? null,
        })
        setCalendarOpen(null)
    }

    const cancelEditing = (): void => {
        setEditing(null)
        setCalendarOpen(null)
    }

    const candidatePhases = useMemo((): ExperimentPhase[] | null => {
        if (!editing) {
            return null
        }

        return applyPhaseUpdates(draftPhases, editing.phaseIndex, {
            name: editing.name,
            reason: editing.reason,
            start_date: editing.startDate,
            end_date: editing.endDate,
        })
    }, [draftPhases, editing])

    const editingValidationError = useMemo(() => {
        if (!candidatePhases) {
            return null
        }

        return validatePhases(candidatePhases)
    }, [candidatePhases])

    const saveEditedPhase = (): void => {
        if (!candidatePhases || editingValidationError) {
            return
        }

        setDraftPhases(candidatePhases)
        setEditing(null)
        setCalendarOpen(null)
    }

    const saveModalValidationError = useMemo(() => validatePhases(draftPhases), [draftPhases])

    const handleSaveChanges = async (): Promise<void> => {
        if (!hasPendingChanges || editing || addingNewPhase || saveModalValidationError) {
            return
        }

        setIsSavingChanges(true)

        try {
            await updateExperiment({ phases: draftPhases })
            setBaselinePhases(clonePhases(draftPhases))
            closeEditPhasesModal()
            refreshExperimentResults(true)
        } catch {
            lemonToast.error('Failed to save phase changes')
        } finally {
            setIsSavingChanges(false)
        }
    }

    const handleDiscardChanges = (): void => {
        setDraftPhases(clonePhases(baselinePhases))
        setEditing(null)
        setAddingNewPhase(null)
        setCalendarOpen(null)
        closeEditPhasesModal()
    }

    const handleStartAddingPhase = (): void => {
        const now = dayjs().toISOString()

        // Set the end date of the current last phase to now
        if (draftPhases.length > 0) {
            const updated = clonePhases(draftPhases)
            updated[updated.length - 1].end_date = now
            setDraftPhases(updated)
        }

        setAddingNewPhase({
            name: '',
            reason: '',
            startDate: now,
        })
        setCalendarOpen(null)
    }

    const addPhaseDisabledReason = useMemo((): string | undefined => {
        if (addingNewPhase) {
            return 'Finish or cancel the phase being added'
        }
        if (hasPendingChanges) {
            return 'Save or discard pending phase edits before adding a new phase'
        }
        if (editing) {
            return 'Save or cancel the phase currently being edited'
        }
        if (!experiment.start_date) {
            return 'Experiment must be running before adding phases'
        }
        return undefined
    }, [addingNewPhase, hasPendingChanges, editing, experiment.start_date])

    const newPhaseValidationError = useMemo(() => {
        if (!addingNewPhase) {
            return undefined
        }
        return validateNewPhase(addingNewPhase.startDate, draftPhases, experiment.start_date, false, false)
    }, [addingNewPhase, draftPhases, experiment.start_date])

    const handleConfirmNewPhase = (): void => {
        if (!addingNewPhase || newPhaseValidationError) {
            return
        }

        addPhase(addingNewPhase.startDate, addingNewPhase.name || undefined, addingNewPhase.reason || undefined)
        setAddingNewPhase(null)
        setCalendarOpen(null)
    }

    const handleCancelNewPhase = (): void => {
        // Revert the end date we set on the last phase
        if (draftPhases.length > 0) {
            const reverted = clonePhases(draftPhases)
            const baselineLastPhase = baselinePhases[baselinePhases.length - 1]
            reverted[reverted.length - 1].end_date = baselineLastPhase?.end_date ?? null
            setDraftPhases(reverted)
        }
        setAddingNewPhase(null)
        setCalendarOpen(null)
    }

    const saveChangesDisabledReason = editing
        ? 'Save or cancel the phase currently being edited'
        : addingNewPhase
          ? 'Finish or cancel the phase being added'
          : !hasPendingChanges
            ? 'No changes to save'
            : saveModalValidationError || undefined

    if (!isEnabled) {
        return null
    }

    const isEditingRow = (row: PhaseRow): boolean => !row.isNew && editing?.phaseIndex === row.index - 1
    const isNewRow = (row: PhaseRow): boolean => !!row.isNew

    return (
        <LemonModal
            isOpen={isEditPhasesModalOpen}
            onClose={handleDiscardChanges}
            title="Manage phases"
            closable={false}
            width="50rem"
            hasUnsavedInput={hasPendingChanges || !!editing || !!addingNewPhase}
            footer={
                <div className="flex items-center justify-between w-full">
                    <LemonButton type="secondary" onClick={handleDiscardChanges} disabled={isSavingChanges}>
                        Discard
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSaveChanges}
                        loading={isSavingChanges}
                        disabledReason={saveChangesDisabledReason}
                    >
                        Save changes
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonTable
                    dataSource={rows}
                    columns={[
                        {
                            title: '#',
                            key: 'index',
                            width: 32,
                            render: (_, row) => <span className="text-secondary">{row.index}</span>,
                        },
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, row) => {
                                if (isEditingRow(row) && editing) {
                                    return (
                                        <div className="flex flex-col gap-1">
                                            <LemonInput
                                                value={editing.name}
                                                onChange={(name) => setEditing({ ...editing, name })}
                                                placeholder={`Phase ${editing.phaseIndex + 1}`}
                                                size="xsmall"
                                            />
                                            <LemonInput
                                                value={editing.reason}
                                                onChange={(reason) => setEditing({ ...editing, reason })}
                                                placeholder="Reason (optional)"
                                                size="xsmall"
                                            />
                                        </div>
                                    )
                                }
                                if (isNewRow(row) && addingNewPhase) {
                                    return (
                                        <div className="flex flex-col gap-1">
                                            <LemonInput
                                                value={addingNewPhase.name}
                                                onChange={(name) => setAddingNewPhase({ ...addingNewPhase, name })}
                                                placeholder={`Phase ${draftPhases.length + 1}`}
                                                size="xsmall"
                                            />
                                            <LemonInput
                                                value={addingNewPhase.reason}
                                                onChange={(reason) => setAddingNewPhase({ ...addingNewPhase, reason })}
                                                placeholder="Reason (optional)"
                                                size="xsmall"
                                            />
                                        </div>
                                    )
                                }
                                return (
                                    <div>
                                        <div>{getPhaseName(row.phase, row.index - 1)}</div>
                                        {row.phase.reason ? (
                                            <div className="text-xs text-secondary">{row.phase.reason}</div>
                                        ) : null}
                                    </div>
                                )
                            },
                        },
                        {
                            title: 'Start date',
                            key: 'startDate',
                            render: (_, row) => {
                                if (isEditingRow(row) && editing) {
                                    const isFirstPhase = editing.phaseIndex === 0
                                    return (
                                        <DatePickerCell
                                            value={editing.startDate}
                                            onChange={(v) => setEditing({ ...editing, startDate: v })}
                                            calendarOpen={calendarOpen}
                                            calendarKey="startDate"
                                            onOpenCalendar={setCalendarOpen}
                                            onCloseCalendar={() => setCalendarOpen(null)}
                                            readOnlyText={isFirstPhase ? 'Locked to experiment start' : undefined}
                                        />
                                    )
                                }
                                if (isNewRow(row) && addingNewPhase) {
                                    return (
                                        <DatePickerCell
                                            value={addingNewPhase.startDate}
                                            onChange={(v) => setAddingNewPhase({ ...addingNewPhase, startDate: v })}
                                            calendarOpen={calendarOpen}
                                            calendarKey="startDate"
                                            onOpenCalendar={setCalendarOpen}
                                            onCloseCalendar={() => setCalendarOpen(null)}
                                        />
                                    )
                                }
                                return (
                                    <span className="font-semibold">
                                        {dayjs(row.phase.start_date).format('MMM D, YYYY')}
                                    </span>
                                )
                            },
                        },
                        {
                            title: 'End date',
                            key: 'endDate',
                            render: (_, row) => {
                                if (isEditingRow(row) && editing) {
                                    const isLastPhase = editing.phaseIndex === draftPhases.length - 1
                                    return (
                                        <DatePickerCell
                                            value={editing.endDate}
                                            onChange={(v) => setEditing({ ...editing, endDate: v })}
                                            calendarOpen={calendarOpen}
                                            calendarKey="endDate"
                                            onOpenCalendar={setCalendarOpen}
                                            onCloseCalendar={() => setCalendarOpen(null)}
                                            readOnlyText={
                                                isLastPhase && editing.endDate === null ? 'Active phase' : undefined
                                            }
                                        />
                                    )
                                }
                                if (isNewRow(row)) {
                                    return <span className="text-secondary text-xs">Active phase</span>
                                }
                                return (
                                    <span className="font-semibold">
                                        {row.phase.end_date ? dayjs(row.phase.end_date).format('MMM D, YYYY') : 'now'}
                                    </span>
                                )
                            },
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 72,
                            render: (_, row) => {
                                if (row.isSynthetic) {
                                    return null
                                }
                                if (isEditingRow(row)) {
                                    return (
                                        <div className="flex gap-1">
                                            <LemonButton
                                                icon={<IconCheck />}
                                                size="xsmall"
                                                tooltip="Save"
                                                onClick={saveEditedPhase}
                                                disabledReason={editingValidationError || undefined}
                                            />
                                            <LemonButton
                                                icon={<IconX />}
                                                size="xsmall"
                                                tooltip="Cancel"
                                                onClick={cancelEditing}
                                            />
                                        </div>
                                    )
                                }
                                if (isNewRow(row)) {
                                    return (
                                        <div className="flex gap-1">
                                            <LemonButton
                                                icon={<IconCheck />}
                                                size="xsmall"
                                                tooltip="Add"
                                                onClick={handleConfirmNewPhase}
                                                disabledReason={newPhaseValidationError}
                                            />
                                            <LemonButton
                                                icon={<IconX />}
                                                size="xsmall"
                                                tooltip="Cancel"
                                                onClick={handleCancelNewPhase}
                                            />
                                        </div>
                                    )
                                }
                                if (editing || addingNewPhase) {
                                    return null
                                }
                                return (
                                    <LemonButton
                                        icon={<IconPencil />}
                                        size="xsmall"
                                        tooltip="Edit"
                                        onClick={() => startEditing(row)}
                                    />
                                )
                            },
                        },
                    ]}
                    size="small"
                    showHeader={true}
                />

                {editingValidationError ? <div className="text-danger text-sm">{editingValidationError}</div> : null}

                {newPhaseValidationError ? <div className="text-danger text-sm">{newPhaseValidationError}</div> : null}

                {isRunning && !addingNewPhase ? (
                    <div>
                        <LemonButton
                            type="secondary"
                            icon={<IconPlus />}
                            size="small"
                            onClick={handleStartAddingPhase}
                            disabledReason={addPhaseDisabledReason}
                        >
                            Add phase
                        </LemonButton>
                    </div>
                ) : null}

                {selectedPhaseIndex != null && selectedPhaseIndex >= draftPhases.length ? (
                    <div className="text-danger text-sm">
                        The selected phase no longer exists. Pick another phase from the selector.
                    </div>
                ) : null}
            </div>
        </LemonModal>
    )
}
