import { useActions, useValues } from 'kea'

import { IconArrowRight, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Label } from 'lib/ui/Label/Label'

import { experimentLogic } from '../experimentLogic'

function formatPhaseOption(
    phase: { start_date: string; end_date: string | null; name?: string },
    index: number
): string {
    const name = phase.name || `Phase ${index + 1}`
    const start = dayjs(phase.start_date).format('MMM D')
    const end = phase.end_date ? dayjs(phase.end_date).format('MMM D') : 'now'
    return `${name}: ${start} – ${end}`
}

export function ExperimentPhaseSelector(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { experiment, selectedPhaseIndex } = useValues(experimentLogic)
    const { setSelectedPhaseIndex, openEditPhasesModal } = useActions(experimentLogic)

    if (!isEnabled) {
        return null
    }

    const phases = experiment.phases || []

    // Determine displayed date range based on selected phase
    const selectedPhase = selectedPhaseIndex != null ? phases[selectedPhaseIndex] : null
    const displayStartDate = selectedPhase?.start_date ?? experiment.start_date
    const displayEndDate = selectedPhase?.end_date ?? experiment.end_date

    const currentLabel =
        selectedPhaseIndex != null && selectedPhase
            ? selectedPhase.name || `Phase ${selectedPhaseIndex + 1}`
            : phases.length > 0
              ? 'All phases'
              : 'Main'

    return (
        <div>
            <Label intent="menu">Phase</Label>
            <div className="flex items-center gap-2">
                <div className="flex items-center gap-2">
                    <div className="w-44">
                        <LemonButton type="secondary" size="xsmall" fullWidth disabledReason="Start date">
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
                        </LemonButton>
                    </div>
                    <IconArrowRight className="text-base" />
                    <div className="w-44">
                        <LemonButton type="secondary" size="xsmall" fullWidth disabledReason="End date">
                            {displayEndDate ? (
                                <TZLabel
                                    time={displayEndDate}
                                    formatDate="MMM DD, YYYY"
                                    formatTime="hh:mm A"
                                    showPopover={true}
                                    noStyles={true}
                                />
                            ) : (
                                'now'
                            )}
                        </LemonButton>
                    </div>
                </div>
                <LemonDropdown
                    overlay={
                        <div className="min-w-48">
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
                            {phases.length > 0 && <div className="border-t my-1" />}
                            <LemonButton fullWidth size="small" onClick={openEditPhasesModal}>
                                Edit phases
                            </LemonButton>
                        </div>
                    }
                >
                    <LemonButton type="secondary" size="xsmall" sideIcon={<IconChevronDown />}>
                        {currentLabel}
                    </LemonButton>
                </LemonDropdown>
            </div>
        </div>
    )
}
