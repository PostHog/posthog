import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { revenueAnalyticsSettingsLogic } from 'products/revenue_analytics/frontend/settings/revenueAnalyticsSettingsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { getFilterLabel } from '~/taxonomy/helpers'
import { AnyPropertyFilter, type CohortType, PropertyOperator, type TeamPublicType, type TeamType } from '~/types'

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
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam, currentTeamLoading, testAccountFilterFrequentMistakes } = useValues(teamLogic)
    const { filterTestAccounts } = useValues(revenueAnalyticsSettingsLogic)
    const { updateFilterTestAccounts } = useActions(revenueAnalyticsSettingsLogic)
    const { cohortsById } = useValues(cohortsModel)

    const testAccountFilterWarningLabels = createTestAccountFilterWarningLabels(currentTeam, cohortsById)

    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const handleChange = (filters: AnyPropertyFilter[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div className="mb-4 flex flex-col gap-2">
            <div className="mb-4 flex flex-col gap-2">
                <LemonBanner type="info">
                    When filtering out internal users by person properties, like email, we recommend creating a Cohort
                    with those properties, and then adding that cohort with a "not in" operator in your ‘Filter out
                    internal and test users’ settings.
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
                label="Enable this filter on all new insights"
                bordered
            />
            <LemonSwitch
                onChange={updateFilterTestAccounts}
                checked={filterTestAccounts}
                disabled={currentTeamLoading}
                label="Filter test accounts out of revenue analytics"
                bordered
            />
        </div>
    )
}

export function ProjectAccountFiltersSetting(): JSX.Element {
    return (
        <>
            <p>
                These filters apply only to queries when the toggle is enabled. Adding filters here does not prevent
                events or recordings being ingested.{' '}
                <Link to="https://posthog.com/tutorials/filter-internal-users">Learn more in our docs</Link>.
            </p>
            <div className="mt-4">
                <strong>Example filters</strong>
                <ul className="list-disc pl-4 mb-2">
                    <li>
                        Add a cohort where "<strong>Email</strong> does not contain <strong>yourcompany.com</strong>" to
                        exclude your team.
                    </li>
                    <li>
                        Add "<strong>Host</strong> does not contain <strong>localhost</strong>" to exclude local
                        environments.
                    </li>
                </ul>
            </div>
            <TestAccountFiltersConfig />
        </>
    )
}
