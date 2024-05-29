import { LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter } from '~/types'

import { filterTestAccountsDefaultsLogic } from './filterTestAccountDefaultsLogic'

function TestAccountFiltersConfig(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { setTeamDefault } = useActions(filterTestAccountsDefaultsLogic)
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
                        Add "<strong>Email</strong> does not contain <strong>yourcompany.com</strong>" to exclude your
                        team.
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
