import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'

import type { ExperimentPhase } from '~/types'

import { experimentLogic } from '../experimentLogic'

interface PhaseRow {
    index: number
    name: string
    phase: ExperimentPhase | null
}

interface EditingState {
    phaseIndex: number
    name: string
    reason: string
    startDate: string
    endDate: string | null
}

function applyPhaseUpdates(
    phases: ExperimentPhase[],
    phaseIndex: number,
    updates: { name?: string; reason?: string; start_date?: string; end_date?: string | null }
): ExperimentPhase[] {
    const updated = phases.map((p) => ({ ...p }))
    const phase = updated[phaseIndex]
    if (updates.name !== undefined) {
        phase.name = updates.name
    }
    if (updates.reason !== undefined) {
        phase.reason = updates.reason
    }
    if (updates.start_date !== undefined) {
        phase.start_date = updates.start_date
        if (phaseIndex > 0) {
            updated[phaseIndex - 1].end_date = updates.start_date
        }
    }
    if (updates.end_date !== undefined) {
        phase.end_date = updates.end_date
        if (updates.end_date !== null && phaseIndex < updated.length - 1) {
            updated[phaseIndex + 1].start_date = updates.end_date
        }
    }
    return updated
}

export function EditPhasesModal(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { isEditPhasesModalOpen, experiment } = useValues(experimentLogic)
    const { closeEditPhasesModal, openAddPhaseModal, setExperiment, updateExperiment, refreshExperimentResults } =
        useActions(experimentLogic)

    const [editing, setEditing] = useState<EditingState | null>(null)
    const [isStartCalendarOpen, setIsStartCalendarOpen] = useState(false)
    const [isEndCalendarOpen, setIsEndCalendarOpen] = useState(false)
    const hasPendingChanges = useRef(false)

    if (!isEnabled) {
        return null
    }

    const phases = experiment.phases || []
    const isRunning = !!experiment.start_date && !experiment.end_date

    const rows: PhaseRow[] =
        phases.length > 0
            ? phases.map((phase, i) => ({
                  index: i + 1,
                  name: phase.name || `Phase ${i + 1}`,
                  phase,
              }))
            : experiment.start_date
              ? [
                    {
                        index: 1,
                        name: 'Main',
                        phase: {
                            start_date: experiment.start_date,
                            end_date: experiment.end_date ?? null,
                        },
                    },
                ]
              : []

    const startEditing = (row: PhaseRow): void => {
        const phase = row.phase
        if (!phase) {
            return
        }
        setEditing({
            phaseIndex: row.index - 1,
            name: phase.name || '',
            reason: phase.reason || '',
            startDate: phase.start_date,
            endDate: phase.end_date ?? null,
        })
    }

    const cancelEditing = (): void => {
        setEditing(null)
        setIsStartCalendarOpen(false)
        setIsEndCalendarOpen(false)
    }

    const handleSave = (): void => {
        if (!editing) {
            return
        }
        const updatedPhases = applyPhaseUpdates(phases, editing.phaseIndex, {
            name: editing.name || undefined,
            reason: editing.reason || undefined,
            start_date: editing.startDate,
            end_date: editing.endDate,
        })
        setExperiment({ phases: updatedPhases })
        hasPendingChanges.current = true
        setEditing(null)
    }

    const handleClose = (): void => {
        if (hasPendingChanges.current) {
            hasPendingChanges.current = false
            updateExperiment({ phases: experiment.phases })
            refreshExperimentResults(true)
        }
        setEditing(null)
        closeEditPhasesModal()
    }

    const hasValidDates = !editing?.endDate || dayjs(editing.startDate).isBefore(dayjs(editing.endDate))

    return (
        <LemonModal
            isOpen={isEditPhasesModalOpen}
            onClose={handleClose}
            title="Edit phases"
            footer={
                <div className="flex justify-end w-full">
                    <LemonButton type="tertiary" onClick={handleClose}>
                        Close
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
                            title: 'NAME',
                            key: 'name',
                            render: (_, row) => row.name,
                        },
                        {
                            title: 'DATES',
                            key: 'dates',
                            render: (_, row) => {
                                if (!row.phase) {
                                    return '–'
                                }
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
                            width: 60,
                            render: (_, row) =>
                                editing?.phaseIndex === row.index - 1 ? null : (
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
                            const isLastPhase = editing.phaseIndex === phases.length - 1
                            return (
                                <div className="flex flex-col gap-3 p-2">
                                    <div>
                                        <Label>Name</Label>
                                        <LemonInput
                                            value={editing.name}
                                            onChange={(val) => setEditing({ ...editing, name: val })}
                                            placeholder={`Phase ${editing.phaseIndex + 1}`}
                                        />
                                    </div>
                                    <div>
                                        <Label>Reason</Label>
                                        <LemonInput
                                            value={editing.reason}
                                            onChange={(val) => setEditing({ ...editing, reason: val })}
                                            placeholder="e.g., Changed rollout to 80%"
                                        />
                                    </div>
                                    <div>
                                        <Label>Start date</Label>
                                        <Popover
                                            actionable
                                            onClickOutside={() => setIsStartCalendarOpen(false)}
                                            visible={isStartCalendarOpen}
                                            overlay={
                                                <LemonCalendarSelect
                                                    value={dayjs(editing.startDate)}
                                                    onChange={(value) => {
                                                        setEditing({
                                                            ...editing,
                                                            startDate: value.toISOString(),
                                                        })
                                                        setIsStartCalendarOpen(false)
                                                    }}
                                                    onClose={() => setIsStartCalendarOpen(false)}
                                                    granularity="minute"
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
                                                            setEditing({
                                                                ...editing,
                                                                endDate: value.toISOString(),
                                                            })
                                                            setIsEndCalendarOpen(false)
                                                        }}
                                                        onClose={() => setIsEndCalendarOpen(false)}
                                                        granularity="minute"
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
                                    <div className="flex gap-2 justify-end">
                                        <LemonButton type="secondary" size="small" onClick={cancelEditing}>
                                            Cancel
                                        </LemonButton>
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={handleSave}
                                            disabledReason={
                                                !hasValidDates ? 'Start date must be before end date' : undefined
                                            }
                                        >
                                            Save
                                        </LemonButton>
                                    </div>
                                </div>
                            )
                        },
                        isRowExpanded: (row) => (editing?.phaseIndex === row.index - 1 ? true : -1),
                        noIndent: true,
                        showRowExpansionToggle: false,
                    }}
                    size="small"
                    showHeader={true}
                />
                {isRunning && (
                    <div>
                        <LemonButton type="primary" size="small" icon={<IconPlus />} onClick={openAddPhaseModal}>
                            New phase
                        </LemonButton>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
