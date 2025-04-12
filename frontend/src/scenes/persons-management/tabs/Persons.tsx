import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { OnboardingStepKey } from 'scenes/onboarding/onboardingLogic'
import { personsSceneLogic } from 'scenes/persons-management/tabs/personsSceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { ProductKey } from '~/types'

export function Persons(): JSX.Element {
    const { query } = useValues(personsSceneLogic)
    const { setQuery } = useActions(personsSceneLogic)
    const { currentTeam } = useValues(teamLogic)

    return (
        <Query
            query={query}
            setQuery={setQuery}
            context={{
                refresh: 'blocking',
                emptyStateHeading: currentTeam?.ingested_event
                    ? 'There are no matching persons for this query'
                    : 'No persons exist because no events have been ingested',
                emptyStateDetail: currentTeam?.ingested_event ? (
                    'Try changing the date range or property filters.'
                ) : (
                    <>
                        Go to the{' '}
                        <Link
                            to={urls.onboarding(ProductKey.PRODUCT_ANALYTICS, OnboardingStepKey.INSTALL)}
                            data-attr="real_project_with_no_events-ingestion_link"
                        >
                            onboarding wizard
                        </Link>{' '}
                        to get things moving
                    </>
                ),
            }}
            dataAttr="persons-table"
        />
    )
}
