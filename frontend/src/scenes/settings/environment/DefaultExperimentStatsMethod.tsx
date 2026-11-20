import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { ExperimentStatsMethod } from '~/types'

import { QuillStatsMethodSelector } from 'products/experiments/frontend/components/QuillStatsMethodSelector'
import { StatsMethodSelector } from 'products/experiments/frontend/components/StatsMethodSelector'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultExperimentStatsMethod(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useQuillSurface()

    const handleChange = (value: ExperimentStatsMethod): void => {
        updateExperimentsConfig({ default_experiment_stats_method: value })
    }

    const statsMethod =
        (experimentsConfig?.default_experiment_stats_method as ExperimentStatsMethod) ?? ExperimentStatsMethod.Bayesian
    const disabledReason = restrictionReason || (experimentsConfigLoading ? 'Loading...' : undefined)

    if (todayRailNav) {
        return <QuillStatsMethodSelector value={statsMethod} onChange={handleChange} disabledReason={disabledReason} />
    }

    return (
        <StatsMethodSelector
            value={statsMethod}
            onChange={handleChange}
            disabled={!!restrictionReason || experimentsConfigLoading}
            disabledReason={disabledReason}
        />
    )
}
