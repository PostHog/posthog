import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, lemonToast } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'

import type { ExperimentPhase } from '~/types'

import { experimentLogic } from '../experimentLogic'

interface PhaseRow {
    index: number
    phase: ExperimentPhase
    isSynthetic?: boolean
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

function getDefaultNewPhaseStartDate(
    phases: ExperimentPhase[],
    experimentStartDate: string | null | undefined
): string {
    const now = dayjs().startOf('minute')
    const lowerBound = phases.length
        ? dayjs(phases[phases.length - 1].start_date).add(1, 'minute')
        : experimentStartDate
          ? dayjs(experimentStartDate).add(1, 'minute')
          : now

    return (lowerBound.isAfter(now) ? now : lowerBound).toISOString()
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

export function EditPhasesModal(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { isEditPhasesModalOpen, experiment, selectedPhaseIndex } = useValues(experimentLogic)
    const { closeEditPhasesModal, addPhase, updateExperiment, refreshExperimentResults } = useActions(experimentLogic)

    const [baselinePhases, setBaselinePhases] = useState<ExperimentPhase[]>([])
    const [draftPhases, setDraftPhases] = useState<ExperimentPhase[]>([])
    const [editing, setEditing] = useState<EditingState | null>(null)
    const [newPhase, setNewPhase] = useState<NewPhaseState>({ name: '', reason: '', startDate: dayjs().toISOString() })
    const [isStartCalendarOpen, setIsStartCalendarOpen] = useState(false)
    const [isEndCalendarOpen, setIsEndCalendarOpen] = useState(false)
    const [isAddCalendarOpen, setIsAddCalendarOpen] = useState(false)
    const [isSavingChanges, setIsSavingChanges] = useState(false)
    const hasOpenedModalRef = useRef(false)

    const isRunning = !!experiment.start_date && !experiment.end_date

    useEffect(() => {
        if (!isEditPhasesModalOpen) {
            hasOpenedModalRef.current = false
            setEditing(null)
            setIsStartCalendarOpen(false)
            setIsEndCalendarOpen(false)
            setIsAddCalendarOpen(false)
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
        setNewPhase({
            name: '',
            reason: '',
            startDate: getDefaultNewPhaseStartDate(phases, experiment.start_date),
        })
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
        setNewPhase({
            name: '',
            reason: '',
            startDate: getDefaultNewPhaseStartDate(syncedPhases, experiment.start_date),
        })
    }, [
        isEditPhasesModalOpen,
        draftPhasesJson,
        baselinePhasesJson,
        serverPhasesJson,
        experiment.phases,
        experiment.start_date,
    ])

    const hasPendingChanges = draftPhasesJson !== baselinePhasesJson

    const rows: PhaseRow[] =
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

    const startEditing = (row: PhaseRow): void => {
        if (row.isSynthetic) {
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
        setIsStartCalendarOpen(false)
        setIsEndCalendarOpen(false)
    }

    const cancelEditing = (): void => {
        setEditing(null)
        setIsStartCalendarOpen(false)
        setIsEndCalendarOpen(false)
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
        setIsStartCalendarOpen(false)
        setIsEndCalendarOpen(false)
    }

    const saveModalValidationError = useMemo(() => validatePhases(draftPhases), [draftPhases])

    const handleSaveChanges = async (): Promise<void> => {
        if (!hasPendingChanges || editing || saveModalValidationError) {
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
        setIsStartCalendarOpen(false)
        setIsEndCalendarOpen(false)
        setIsAddCalendarOpen(false)
        closeEditPhasesModal()
    }

    const addPhaseDisabledReason = useMemo(
        () => validateNewPhase(newPhase.startDate, draftPhases, experiment.start_date, hasPendingChanges, !!editing),
        [newPhase.startDate, draftPhases, experiment.start_date, hasPendingChanges, editing]
    )

    const handleAddPhase = (): void => {
        if (addPhaseDisabledReason) {
            return
        }

        addPhase(newPhase.startDate, newPhase.name || undefined, newPhase.reason || undefined)
    }

    const saveChangesDisabledReason = editing
        ? 'Save or cancel the phase currently being edited'
        : !hasPendingChanges
          ? 'No changes to save'
          : saveModalValidationError || undefined

    if (!isEnabled) {
        return null
    }

    return (
        <LemonModal
            isOpen={isEditPhasesModalOpen}
            onClose={handleDiscardChanges}
            title="Manage phases"
            closable={false}
            hasUnsavedInput={hasPendingChanges || !!editing}
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
                            title: '',
                            key: 'index',
                            width: 32,
                            render: (_, row) => <span className="text-secondary">{row.index}</span>,
                        },
                        {
                            title: 'Name',
                            key: 'name',
                            render: (_, row) => getPhaseName(row.phase, row.index - 1),
                        },
                        {
                            title: 'Dates',
                            key: 'dates',
                            render: (_, row) => {
                                const start = dayjs(row.phase.start_date).format('MMM D, YYYY')
                                const end = row.phase.end_date ? dayjs(row.phase.end_date).format('MMM D, YYYY') : null

                                return (
                                    <span>
                                        <strong>{start}</strong> to <strong>{end ?? 'now'}</strong>
                                    </span>
                                )
                            },
                        },
                        {
                            title: '',
                            key: 'actions',
                            width: 64,
                            render: (_, row) =>
                                row.isSynthetic || editing?.phaseIndex === row.index - 1 ? null : (
                                    <LemonButton type="secondary" size="xsmall" onClick={() => startEditing(row)}>
                                        Edit
                                    </LemonButton>
                                ),
                        },
                    ]}
                    expandable={{
                        expandedRowRender: (row) => {
                            if (!editing || editing.phaseIndex !== row.index - 1) {
                                return null
                            }

                            const isLastPhase = editing.phaseIndex === draftPhases.length - 1
                            const isFirstPhase = editing.phaseIndex === 0

                            return (
                                <div className="flex flex-col gap-3 p-2">
                                    <div>
                                        <Label>Name</Label>
                                        <LemonInput
                                            value={editing.name}
                                            onChange={(name) => setEditing({ ...editing, name })}
                                            placeholder={`Phase ${editing.phaseIndex + 1}`}
                                        />
                                    </div>
                                    <div>
                                        <Label>Reason</Label>
                                        <LemonInput
                                            value={editing.reason}
                                            onChange={(reason) => setEditing({ ...editing, reason })}
                                            placeholder="e.g., Changed rollout to 80%"
                                        />
                                    </div>
                                    <div>
                                        <Label>Start date</Label>
                                        {isFirstPhase ? (
                                            <span className="text-secondary text-sm">
                                                Phase 1 starts when the experiment starts
                                            </span>
                                        ) : (
                                            <Popover
                                                actionable
                                                onClickOutside={() => setIsStartCalendarOpen(false)}
                                                visible={isStartCalendarOpen}
                                                overlay={
                                                    <LemonCalendarSelect
                                                        value={dayjs(editing.startDate)}
                                                        onChange={(value) => {
                                                            setEditing({ ...editing, startDate: value.toISOString() })
                                                            setIsStartCalendarOpen(false)
                                                        }}
                                                        onClose={() => setIsStartCalendarOpen(false)}
                                                        granularity="minute"
                                                        selectionPeriod="past"
                                                    />
                                                }
                                            >
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    onClick={() => setIsStartCalendarOpen(true)}
                                                >
                                                    {dayjs(editing.startDate).format('MMM D, YYYY hh:mm A')}
                                                </LemonButton>
                                            </Popover>
                                        )}
                                    </div>
                                    <div>
                                        <Label>End date</Label>
                                        {isLastPhase && editing.endDate === null ? (
                                            <span className="text-secondary text-sm">
                                                This is the current active phase (no end date)
                                            </span>
                                        ) : (
                                            <Popover
                                                actionable
                                                onClickOutside={() => setIsEndCalendarOpen(false)}
                                                visible={isEndCalendarOpen}
                                                overlay={
                                                    <LemonCalendarSelect
                                                        value={editing.endDate ? dayjs(editing.endDate) : dayjs()}
                                                        onChange={(value) => {
                                                            setEditing({ ...editing, endDate: value.toISOString() })
                                                            setIsEndCalendarOpen(false)
                                                        }}
                                                        onClose={() => setIsEndCalendarOpen(false)}
                                                        granularity="minute"
                                                        selectionPeriod="past"
                                                    />
                                                }
                                            >
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    onClick={() => setIsEndCalendarOpen(true)}
                                                >
                                                    {editing.endDate
                                                        ? dayjs(editing.endDate).format('MMM D, YYYY hh:mm A')
                                                        : 'Select date'}
                                                </LemonButton>
                                            </Popover>
                                        )}
                                    </div>
                                    {editingValidationError ? (
                                        <div className="text-danger text-sm">{editingValidationError}</div>
                                    ) : null}
                                    <div className="flex justify-end gap-2">
                                        <LemonButton type="secondary" size="small" onClick={cancelEditing}>
                                            Cancel
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={saveEditedPhase}
                                            disabledReason={editingValidationError || undefined}
                                        >
                                            Save phase
                                        </LemonButton>
                                    </div>
                                </div>
                            )
                        },
                        isRowExpanded: (row) => editing?.phaseIndex === row.index - 1,
                        expandedRowClassName: 'bg-white',
                        noIndent: true,
                        showRowExpansionToggle: false,
                    }}
                    size="small"
                    showHeader={true}
                />

                {isRunning ? (
                    <div className="border rounded p-3 bg-bg-light flex flex-col gap-3">
                        <Label>Add phase</Label>
                        <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2 items-end">
                            <div>
                                <Label>Start date</Label>
                                <Popover
                                    actionable
                                    onClickOutside={() => setIsAddCalendarOpen(false)}
                                    visible={isAddCalendarOpen}
                                    overlay={
                                        <LemonCalendarSelect
                                            value={dayjs(newPhase.startDate)}
                                            onChange={(value) => {
                                                setNewPhase({ ...newPhase, startDate: value.toISOString() })
                                                setIsAddCalendarOpen(false)
                                            }}
                                            onClose={() => setIsAddCalendarOpen(false)}
                                            granularity="minute"
                                            selectionPeriod="past"
                                        />
                                    }
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        onClick={() => setIsAddCalendarOpen(true)}
                                    >
                                        {dayjs(newPhase.startDate).format('MMM D, YYYY hh:mm A')}
                                    </LemonButton>
                                </Popover>
                            </div>
                            <div>
                                <Label>Name (optional)</Label>
                                <LemonInput
                                    value={newPhase.name}
                                    onChange={(name) => setNewPhase({ ...newPhase, name })}
                                    placeholder={`Phase ${draftPhases.length + 1}`}
                                />
                            </div>
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={handleAddPhase}
                                disabledReason={addPhaseDisabledReason}
                            >
                                Add phase
                            </LemonButton>
                        </div>
                        <div>
                            <Label>Reason (optional)</Label>
                            <LemonInput
                                value={newPhase.reason}
                                onChange={(reason) => setNewPhase({ ...newPhase, reason })}
                                placeholder="e.g., Changed rollout to 80%"
                            />
                        </div>
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
