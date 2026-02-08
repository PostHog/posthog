import { useActions, useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Link } from 'lib/lemon-ui/Link'
import { CONFIDENCE_LEVEL_OPTIONS } from 'scenes/experiments/constants'

import { teamLogic } from '~/scenes/teamLogic'

export function DefaultExperimentConfidenceLevel(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    const handleChange = (value: number | null): void => {
        if (value === null) {
            return
        }
        updateCurrentTeam({ default_experiment_confidence_level: value })
    }

    const currentValue = currentTeam?.default_experiment_confidence_level
        ? parseFloat(String(currentTeam.default_experiment_confidence_level))
        : 0.95

    return (
        <div>
            <div className="flex flex-col space-y-2">
                <LemonLabel className="text-base">Default confidence level</LemonLabel>
                <p className="text-secondary">
                    Higher confidence level reduces false positives but requires more data. Can be overridden per
                    experiment. <Link to="https://posthog.com/docs/experiments/statistics-frequentist">Learn more</Link>
                    .
                </p>
                <div className="space-y-2">
                    <LemonSelect
                        value={currentValue}
                        onChange={handleChange}
                        options={CONFIDENCE_LEVEL_OPTIONS}
                        disabledReason={restrictionReason || (currentTeamLoading ? 'Loading...' : undefined)}
                        data-attr="team-default-experiment-confidence-level"
                        className="w-24"
                    />
                </div>
            </div>
        </div>
    )
}
