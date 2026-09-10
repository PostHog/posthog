import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { cohortsStaffToolsLogic, parseCohortIds } from './cohortsStaffToolsLogic'
import { StaffCohortsTable } from './StaffCohortsTable'

export const scene: SceneExport = {
    component: CohortsStaffToolsScene,
    logic: cohortsStaffToolsLogic,
}

function LookupPanel(): JSX.Element {
    const { cohortIdsInput, lookupResponse, lookedUpCohorts, lookupResponseLoading } = useValues(cohortsStaffToolsLogic)
    const { setCohortIdsInput, lookUpCohorts, recalculateCohorts } = useActions(cohortsStaffToolsLogic)

    const hasIds = parseCohortIds(cohortIdsInput).length > 0
    const notFound = lookupResponse?.not_found_cohort_ids ?? []

    return (
        <div className="space-y-2">
            <h3 className="mb-0">Look up cohorts</h3>
            <div className="flex items-center gap-2">
                <LemonInput
                    className="flex-1"
                    placeholder="Cohort ids, comma-separated (e.g. 128418, 34012)"
                    aria-label="Cohort ids to look up"
                    value={cohortIdsInput}
                    onChange={setCohortIdsInput}
                    onPressEnter={() => hasIds && !lookupResponseLoading && lookUpCohorts()}
                    data-attr="cohorts-staff-lookup-input"
                />
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => lookUpCohorts()}
                    loading={lookupResponseLoading}
                    disabledReason={!hasIds ? 'Enter at least one cohort id' : undefined}
                >
                    Look up
                </LemonButton>
            </div>
            {notFound.length > 0 && (
                <LemonBanner type="warning">Cohort ids not found: {notFound.join(', ')}</LemonBanner>
            )}
            <StaffCohortsTable
                cohorts={lookedUpCohorts}
                loading={lookupResponseLoading}
                emptyState="Enter one or more cohort ids to inspect their calculation state."
                onRecalculate={(cohortId) => recalculateCohorts({ cohortIds: [cohortId] })}
            />
        </div>
    )
}

function StuckCohortsPanel(): JSX.Element {
    const { stuckCohorts, stuckResponse, stuckResponseLoading } = useValues(cohortsStaffToolsLogic)
    const { loadStuckCohorts, recalculateCohorts } = useActions(cohortsStaffToolsLogic)

    const totalCount = stuckResponse?.total_count ?? 0

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <h3 className="mb-0">Stuck cohorts</h3>
                {totalCount > stuckCohorts.length && (
                    <span className="text-secondary">
                        showing {stuckCohorts.length} of {totalCount}
                    </span>
                )}
                <LemonButton
                    type="tertiary"
                    size="small"
                    className="ml-auto"
                    loading={stuckResponseLoading}
                    onClick={() => loadStuckCohorts()}
                >
                    Refresh
                </LemonButton>
            </div>
            <p className="text-secondary mb-0">
                Dynamic cohorts marked as calculating whose last completed calculation is over an hour old. Their
                calculation task likely died without resetting the flag.
            </p>
            <StaffCohortsTable
                cohorts={stuckCohorts}
                loading={stuckResponseLoading}
                emptyState="No stuck cohorts right now."
                onRecalculate={(cohortId) => recalculateCohorts({ cohortIds: [cohortId] })}
            />
        </div>
    )
}

export function CohortsStaffToolsScene(): JSX.Element {
    const { user } = useValues(userLogic)

    if (!user?.is_staff) {
        return <AccessDenied object="page" reason="This page is only accessible to staff users." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name="Cohorts staff tools"
                description="Look up cohorts across all teams, inspect their calculation state, and force recalculation of stuck cohorts."
                resourceType={{ type: 'cohort' }}
                actions={
                    <LemonButton type="secondary" size="small" to={urls.featureFlagsStaffTools()}>
                        Flags staff tools
                    </LemonButton>
                }
            />
            <div className="space-y-6">
                <LookupPanel />
                <StuckCohortsPanel />
            </div>
        </SceneContent>
    )
}
