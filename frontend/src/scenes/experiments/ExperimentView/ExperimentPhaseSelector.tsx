import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { experimentLogic } from '../experimentLogic'

function formatPhaseLabel(
    phase: { start_date: string; end_date: string | null; name?: string },
    index: number
): string {
    const name = phase.name || `Phase ${index + 1}`
    const start = dayjs(phase.start_date).format('MMM D')
    const end = phase.end_date ? dayjs(phase.end_date).format('MMM D') : 'present'
    return `${name}: ${start} – ${end}`
}

export function ExperimentPhaseSelector(): JSX.Element | null {
    const isEnabled = useFeatureFlag('EXPERIMENT_PHASES')
    const { experiment, selectedPhaseIndex } = useValues(experimentLogic)
    const { setSelectedPhaseIndex, openAddPhaseModal } = useActions(experimentLogic)

    if (!isEnabled) {
        return null
    }

    const phases = experiment.phases || []
    const isRunning = !!experiment.start_date && !experiment.end_date

    if (phases.length === 0 && !isRunning) {
        return null
    }

    const options = [
        { value: null as number | null, label: 'All phases' },
        ...phases.map((phase, i) => ({
            value: i as number | null,
            label: formatPhaseLabel(phase, i),
        })),
    ]

    return (
        <div className="flex items-center gap-2">
            {phases.length > 0 && (
                <LemonSelect
                    size="xsmall"
                    value={selectedPhaseIndex}
                    onChange={(value) => setSelectedPhaseIndex(value)}
                    options={options}
                />
            )}
            {isRunning && (
                <LemonButton type="secondary" size="xsmall" icon={<IconPlus />} onClick={openAddPhaseModal}>
                    Add phase
                </LemonButton>
            )}
        </div>
    )
}
