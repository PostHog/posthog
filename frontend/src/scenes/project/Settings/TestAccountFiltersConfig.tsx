import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'
import { LemonSwitch } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'

export function TestAccountFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam, currentTeamLoading, testAccountFilterWarning } = useValues(teamLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const handleChange = (filters: AnyPropertyFilter[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div className="mb-4 flex flex-col gap-2">
            <div className="mb-4">
                {!!testAccountFilterWarning && (
                    <AlertMessage type="warning" className={'m-2'}>
                        {testAccountFilterWarning}
                    </AlertMessage>
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
                    localStorage.setItem('default_filter_test_accounts', checked.toString())
                    updateCurrentTeam({ test_account_filters_default_checked: checked })
                }}
                checked={!!currentTeam?.test_account_filters_default_checked}
                disabled={currentTeamLoading}
                label="Enable this filter on all new insights"
                bordered
            />
        </div>
    )
}
