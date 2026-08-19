import { useActions, useValues } from 'kea'

import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, type CohortType, PropertyOperator, type TeamPublicType, type TeamType } from '~/types'

import { revenueAnalyticsSettingsLogic } from 'products/revenue_analytics/frontend/settings/revenueAnalyticsSettingsLogic'

import { applyTestAccountFilterLogic } from './applyTestAccountFilterLogic'
import { filterTestAccountsDefaultsLogic } from './filterTestAccountDefaultsLogic'

function createTestAccountFilterWarningLabels(
    currentTeam: TeamPublicType | TeamType | null,
    cohortsById: Partial<Record<number | string, CohortType>>
): string[] | null {
    if (!currentTeam) {
        return null
    }
    const positiveFilterOperators = [
        PropertyOperator.Exact,
        PropertyOperator.IContains,
        PropertyOperator.Regex,
        PropertyOperator.IsSet,
        PropertyOperator.In,
    ]
    const positiveFilters = []
    for (const filter of currentTeam.test_account_filters || []) {
        if ('operator' in filter && !!filter.operator && positiveFilterOperators.includes(filter.operator)) {
            positiveFilters.push(filter)
        }
    }

    return positiveFilters.map((filter) => {
        if (!!filter.type && !!filter.key) {
            // person properties can be checked for a label as if they were event properties
            // so, we can check each acceptable type and see if it returns a value
            if (filter.type === 'cohort') {
                return `Cohort ${cohortsById[filter.value]?.name || filter.value}`
            }
            return (
                getFilterLabel(filter.key, PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type]) ||
                filter.key
            )
        }
        return filter.key
    })
}

function TestAccountFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { setTeamDefault } = useActions(filterTestAccountsDefaultsLogic)
    const { applyToExistingInsights } = useActions(applyTestAccountFilterLogic)
    const { bulkSetResponseLoading } = useValues(applyTestAccountFilterLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam, currentTeamLoading, testAccountFilterFrequentMistakes } = useValues(teamLogic)
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)
    const { cohortsById } = useValues(cohortsModel)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const testAccountFilterWarningLabels = createTestAccountFilterWarningLabels(currentTeam, cohortsById)
    const noFiltersReason = currentTeam?.test_account_filters?.length ? null : 'Add at least one filter above first'

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const handleChange = (filters: AnyPropertyFilter[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div className="mb-4 flex flex-col gap-2">
            <div className="mb-4 flex flex-col gap-2">
                <LemonBanner type="info">
                    When filtering out internal users, inline person property filters (e.g., "email does not contain
                    your-domain.com") work everywhere, including real-time CDP destinations. Alternatively, you can
                    create a cohort and add it with a "not in" operator - this works well for analytics queries
                    (insights, dashboards) and also works in CDP destinations if the cohort contains{' '}
                    <strong>exclusively person property filters</strong>. Cohorts with behavioral filters or no
                    properties defined will cause CDP destinations to error.
                </LemonBanner>
                {!!testAccountFilterWarningLabels && testAccountFilterWarningLabels.length > 0 && (
                    <LemonBanner type="warning" className="m-2">
                        <p>
                            You've added an <strong>inclusive</strong> filter, which means only matching events will be
                            included. Filters are normally <strong>exclusive</strong>, such as <i>does not contain</i>,
                            to filter out unwanted results.
                        </p>
                        <p>Inclusive filters are currently set for the following properties: </p>
                        <ul className="list-disc">
                            {testAccountFilterWarningLabels.map((l, i) => (
                                <li key={i} className="ml-4">
                                    {l}
                                </li>
                            ))}
                        </ul>
                    </LemonBanner>
                )}
                {!!testAccountFilterFrequentMistakes && testAccountFilterFrequentMistakes.length > 0 && (
                    <LemonBanner type="warning" className="m-2">
                        <p>Your filter contains a setting that is likely to exclude or include unexpected users.</p>
                        <ul className="list-disc">
                            {testAccountFilterFrequentMistakes.map(({ key, type, fix }, i) => (
                                <li key={i} className="ml-4">
                                    {key} is a {type} property, but {fix}.
                                </li>
                            ))}
                        </ul>
                    </LemonBanner>
                )}
                {currentTeam && (
                    <PropertyFilters
                        pageKey="testaccountfilters"
                        propertyFilters={currentTeam?.test_account_filters}
                        onChange={handleChange}
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        disabledReason={restrictedReason ?? undefined}
                    />
                )}
            </div>
            <LemonSwitch
                onChange={(checked) => {
                    updateCurrentTeam({ test_account_filters_default_checked: checked })
                    setTeamDefault(checked)
                }}
                checked={!!currentTeam?.test_account_filters_default_checked}
                disabled={currentTeamLoading}
                disabledReason={restrictedReason}
                label="Enable this filter on all new insights"
                bordered
            />
            <div className="flex">
                <LemonButton
                    type="secondary"
                    size="small"
                    data-attr="apply-test-account-filter-to-existing-insights"
                    loading={bulkSetResponseLoading}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason ?? noFiltersReason}
                    onClick={() => {
                        const enabled = !!currentTeam?.test_account_filters_default_checked
                        LemonDialog.open({
                            title: `Turn this filter ${enabled ? 'on' : 'off'} for every existing insight?`,
                            description: (
                                <>
                                    The setting above only decides the default for new insights. This applies it to the
                                    insights you already have. SQL insights have no such filter, so they stay as they
                                    are, and so do insights you can't edit. Dashboards follow their insights unless a
                                    dashboard sets its own override.
                                    <br />
                                    <br />
                                    There's no undo. Running it the other way later would also flip insights that were
                                    set differently before.
                                </>
                            ),
                            primaryButton: {
                                children: `Turn it ${enabled ? 'on' : 'off'}`,
                                onClick: () => applyToExistingInsights(enabled),
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Apply to existing insights
                </LemonButton>
            </div>
            <LemonSwitch
                onChange={updateFilterTestAccounts}
                checked={filterTestAccounts}
                disabled={currentTeamLoading}
                disabledReason={restrictedReason}
                label="Filter out internal and test users from revenue analytics"
                bordered
            />
        </div>
    )
}

export function ProjectAccountFiltersSetting(): JSX.Element {
    return <TestAccountFiltersConfig />
}
