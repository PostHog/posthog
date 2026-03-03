import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'

import { experimentLogic } from '../experimentLogic'

export function EditPhaseModal(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { editingPhaseIndex, experiment } = useValues(experimentLogic)
    const { closeEditPhaseModal, updatePhase } = useActions(experimentLogic)

    const [name, setName] = useState('')
    const [reason, setReason] = useState('')
    const [startDate, setStartDate] = useState<string>('')
    const [endDate, setEndDate] = useState<string | null>(null)
    const [isStartCalendarOpen, setIsStartCalendarOpen] = useState(false)
    const [isEndCalendarOpen, setIsEndCalendarOpen] = useState(false)

    const phases = experiment.phases || []
    const phase = editingPhaseIndex !== null ? phases[editingPhaseIndex] : null
    const isLastPhase = editingPhaseIndex !== null && editingPhaseIndex === phases.length - 1
    const isOpen = editingPhaseIndex !== null

    useEffect(() => {
        if (phase) {
            setName(phase.name || '')
            setReason(phase.reason || '')
            setStartDate(phase.start_date)
            setEndDate(phase.end_date ?? null)
        }
    }, [editingPhaseIndex])

    if (!isEnabled || !isOpen || !phase) {
        return null
    }

    const hasValidDates = !endDate || dayjs(startDate).isBefore(dayjs(endDate))

    const handleSubmit = (): void => {
        if (editingPhaseIndex === null) {
            return
        }
        updatePhase(editingPhaseIndex, {
            name: name || undefined,
            reason: reason || undefined,
            start_date: startDate,
            end_date: endDate,
        })
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeEditPhaseModal}
            title={`Edit ${phase.name || `Phase ${editingPhaseIndex + 1}`}`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeEditPhaseModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={handleSubmit}
                        disabledReason={!hasValidDates ? 'Start date must be before end date' : undefined}
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <div>
                    <Label>Name</Label>
                    <LemonInput value={name} onChange={setName} placeholder={`Phase ${(editingPhaseIndex ?? 0) + 1}`} />
                </div>
                <div>
                    <Label>Reason</Label>
                    <LemonInput value={reason} onChange={setReason} placeholder="e.g., Changed rollout to 80%" />
                </div>
                <div>
                    <Label>Start date</Label>
                    <Popover
                        actionable
                        onClickOutside={() => setIsStartCalendarOpen(false)}
                        visible={isStartCalendarOpen}
                        overlay={
                            <LemonCalendarSelect
                                value={dayjs(startDate)}
                                onChange={(value) => {
                                    setStartDate(value.toISOString())
                                    setIsStartCalendarOpen(false)
                                }}
                                onClose={() => setIsStartCalendarOpen(false)}
                                granularity="minute"
                            />
                        }
                    >
                        <LemonButton type="secondary" size="small" onClick={() => setIsStartCalendarOpen(true)}>
                            {dayjs(startDate).format('MMM D, YYYY hh:mm A')}
                        </LemonButton>
                    </Popover>
                </div>
                <div>
                    <Label>End date</Label>
                    {isLastPhase && endDate === null ? (
                        <span className="text-secondary text-sm">This is the current active phase (no end date)</span>
                    ) : (
                        <Popover
                            actionable
                            onClickOutside={() => setIsEndCalendarOpen(false)}
                            visible={isEndCalendarOpen}
                            overlay={
                                <LemonCalendarSelect
                                    value={endDate ? dayjs(endDate) : dayjs()}
                                    onChange={(value) => {
                                        setEndDate(value.toISOString())
                                        setIsEndCalendarOpen(false)
                                    }}
                                    onClose={() => setIsEndCalendarOpen(false)}
                                    granularity="minute"
                                />
                            }
                        >
                            <LemonButton type="secondary" size="small" onClick={() => setIsEndCalendarOpen(true)}>
                                {endDate ? dayjs(endDate).format('MMM D, YYYY hh:mm A') : 'Select date'}
                            </LemonButton>
                        </Popover>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}
