import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { groupsModel } from '~/models/groupsModel'
import { LemonSwitch } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'

export function TestAccountFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { reportTestAccountFiltersUpdated } = useActions(eventUsageLogic)
    const { currentTeam, currentTeamLoading, testAccountFilterWarningLabels, testAccountFilterFrequentMistakes } =
        useValues(teamLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    const handleChange = (filters: AnyPropertyFilter[]): void => {
        updateCurrentTeam({ test_account_filters: filters })
        reportTestAccountFiltersUpdated(filters)
    }

    return (
        <div className="mb-4 flex flex-col gap-2">
            <div className="mb-4">
                {!!testAccountFilterWarningLabels && testAccountFilterWarningLabels.length > 0 && (
                    <AlertMessage type="warning" className="m-2">
                        <p>
                            Positive filters here mean only events or persons matching these filters will be included.
                            Internal and test account filters are normally excluding filters like does not equal or does
                            not contain.
                        </p>
                        <p>Positive filters are currently set for the following properties: </p>
                        <ul className="list-disc">
                            {testAccountFilterWarningLabels.map((l, i) => (
                                <li key={i} className="ml-4">
                                    {l}
                                </li>
                            ))}
                        </ul>
                    </AlertMessage>
                )}
                {!!testAccountFilterFrequentMistakes && testAccountFilterFrequentMistakes.length > 0 && (
                    <AlertMessage type="warning" className="m-2">
                        <p>Your filter contains a setting that is likely to exclude or include unexpected users.</p>
                        <ul className="list-disc">
                            {testAccountFilterFrequentMistakes.map(({ key, type, fix }, i) => (
                                <li key={i} className="ml-4">
                                    {key} is a {type} property, but {fix}.
                                </li>
                            ))}
                        </ul>
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
