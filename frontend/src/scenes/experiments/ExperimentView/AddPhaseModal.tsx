import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCalendarSelect } from 'lib/lemon-ui/LemonCalendar/LemonCalendarSelect'
import { Popover } from 'lib/lemon-ui/Popover'
import { Label } from 'lib/ui/Label/Label'

import { experimentLogic } from '../experimentLogic'

export function AddPhaseModal(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { isAddPhaseModalOpen, experiment } = useValues(experimentLogic)
    const { closeAddPhaseModal, addPhase } = useActions(experimentLogic)

    const [phaseStartDate, setPhaseStartDate] = useState<string>(dayjs().toISOString())
    const [name, setName] = useState<string>('')
    const [reason, setReason] = useState<string>('')
    const [isCalendarOpen, setIsCalendarOpen] = useState(false)

    if (!isEnabled) {
        return null
    }

    const phases = experiment.phases || []
    const phaseNumber = phases.length > 0 ? phases.length + 1 : 2

    const handleSubmit = (): void => {
        addPhase(phaseStartDate, name || `Phase ${phaseNumber}`, reason || undefined)
        setName('')
        setReason('')
        setPhaseStartDate(dayjs().toISOString())
    }

    return (
        <LemonModal
            isOpen={isAddPhaseModalOpen}
            onClose={closeAddPhaseModal}
            title="Add phase"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeAddPhaseModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSubmit}>
                        Add phase
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <p className="text-secondary">
                    Adding a phase splits the experiment timeline at the chosen date. Results can then be viewed
                    independently for each phase.
                </p>
                <div>
                    <Label>Phase start date</Label>
                    <Popover
                        actionable
                        onClickOutside={() => setIsCalendarOpen(false)}
                        visible={isCalendarOpen}
                        overlay={
                            <LemonCalendarSelect
                                value={dayjs(phaseStartDate)}
                                onChange={(value) => {
                                    setPhaseStartDate(value.toISOString())
                                    setIsCalendarOpen(false)
                                }}
                                onClose={() => setIsCalendarOpen(false)}
                                granularity="minute"
                            />
                        }
                    >
                        <LemonButton type="secondary" size="small" onClick={() => setIsCalendarOpen(true)}>
                            {dayjs(phaseStartDate).format('MMM D, YYYY hh:mm A')}
                        </LemonButton>
                    </Popover>
                </div>
                <div>
                    <Label>Name (optional)</Label>
                    <LemonInput value={name} onChange={setName} placeholder={`Phase ${phaseNumber}`} />
                </div>
                <div>
                    <Label>Reason (optional)</Label>
                    <LemonInput value={reason} onChange={setReason} placeholder="e.g., Changed rollout to 80%" />
                </div>
            </div>
        </LemonModal>
    )
}
