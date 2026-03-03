import { useActions, useValues } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Label } from 'lib/ui/Label/Label'

import { experimentLogic } from '../experimentLogic'

function getPhaseName(phase: { name?: string }, index: number): string {
    return phase.name || `Phase ${index + 1}`
}

function formatPhaseOption(
    phase: { start_date: string; end_date: string | null; name?: string },
    index: number
): string {
    const name = getPhaseName(phase, index)
    const start = dayjs(phase.start_date).format('MMM D')
    const end = phase.end_date ? dayjs(phase.end_date).format('MMM D') : 'now'
    return `${name}: ${start} - ${end}`
}

export function ExperimentPhaseSelector(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { experiment, selectedPhaseIndex } = useValues(experimentLogic)
    const { setSelectedPhaseIndex, openEditPhasesModal } = useActions(experimentLogic)

    if (!isEnabled) {
        return null
    }

    const phases = experiment.phases || []
    const selectedPhase = selectedPhaseIndex != null ? phases[selectedPhaseIndex] : null
    const selectedPhaseLabel = selectedPhase ? getPhaseName(selectedPhase, selectedPhaseIndex ?? 0) : 'All phases'
    const displayStartDate = selectedPhase?.start_date ?? experiment.start_date
    const displayEndDate = selectedPhase?.end_date ?? experiment.end_date

    return (
        <div>
            <Label intent="menu">Phase</Label>
            <div className="flex items-center gap-2">
                <LemonDropdown
                    matchWidth={false}
                    overlay={
                        <div className="min-w-56">
                            <LemonButton
                                fullWidth
                                size="small"
                                active={selectedPhaseIndex === null}
                                onClick={() => setSelectedPhaseIndex(null)}
                            >
                                All phases
                            </LemonButton>
                            {phases.map((phase, i) => (
                                <LemonButton
                                    key={i}
                                    fullWidth
                                    size="small"
                                    active={selectedPhaseIndex === i}
                                    onClick={() => setSelectedPhaseIndex(i)}
                                >
                                    {formatPhaseOption(phase, i)}
                                </LemonButton>
                            ))}
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="xsmall">
                        <span className="flex items-center gap-1.5">
                            <span className="font-medium">{selectedPhaseLabel}</span>
                            <span className="text-secondary">-</span>
                            {displayStartDate ? (
                                <TZLabel
                                    time={displayStartDate}
                                    formatDate="MMM DD, YYYY"
                                    formatTime="hh:mm A"
                                    showPopover={true}
                                    noStyles={true}
                                />
                            ) : (
                                'No date'
                            )}
                            <IconArrowRight className="text-xs" />
                            {displayEndDate ? (
                                <TZLabel
                                    time={displayEndDate}
                                    formatDate="MMM DD, YYYY"
                                    formatTime="hh:mm A"
                                    showPopover={true}
                                    noStyles={true}
                                />
                            ) : (
                                <span>now</span>
                            )}
                        </span>
                    </LemonButton>
                </LemonDropdown>
                <LemonButton type="secondary" size="xsmall" onClick={openEditPhasesModal}>
                    Manage phases
                </LemonButton>
            </div>
        </div>
    )
}
